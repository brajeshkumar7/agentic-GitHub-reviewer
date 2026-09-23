"""Bounded HTTPS page fetcher that rejects private and local destinations."""

from __future__ import annotations

import http.client
import ipaddress
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import (
    HTTPSHandler,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from pydantic import ValidationError

from research_agent.limits import (
    URL_FETCH_MAX_REDIRECTS,
    URL_FETCH_MAX_RESPONSE_BYTES,
    URL_FETCH_MAX_TEXT_CHARS,
    URL_FETCH_TIMEOUT_SECONDS,
)
from research_agent.models import (
    FailureCategory,
    FetchedPage,
    Retryability,
    ToolCall,
    ToolName,
    ToolResult,
    ToolResultStatus,
    URLFetchInput,
)
from research_agent.tools.base import failed_tool_result
from research_agent.tools.safe_url import (
    UnsafeDestination,
    public_destination_addresses,
    validate_public_https_url,
)


class ResponseTooLarge(ValueError):
    """Raised when an upstream response exceeds the configured byte cap."""


class InvalidPageResponse(ValueError):
    """Raised when a successful HTTP payload is not a usable page."""


@dataclass(frozen=True)
class FetchResponse:
    status_code: int
    content_type: str
    charset: str | None
    final_url: str
    body: bytes


class _PublicPinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a validated numeric IP while retaining hostname TLS checks."""

    def _create_connection(
        self,
        address: tuple[str, int],
        timeout: float | object = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        host, port = address
        candidates = public_destination_addresses(host, int(port))
        last_error: OSError | None = None
        for candidate in candidates:
            try:
                parsed = ipaddress.ip_address(candidate)
                target = (str(parsed), int(port))
                return socket.create_connection(target, timeout, source_address)
            except OSError as error:
                last_error = error
        if last_error is not None:
            raise last_error
        raise UnsafeDestination("host has no public address")


class _PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, request: Request) -> http.client.HTTPResponse:
        return self.do_open(
            _PublicPinnedHTTPSConnection,
            request,
            context=self._context,
            check_hostname=self._check_hostname,
        )


class _SafeRedirectHandler(HTTPRedirectHandler):
    max_redirections = URL_FETCH_MAX_REDIRECTS
    max_repeats = URL_FETCH_MAX_REDIRECTS

    def redirect_request(
        self,
        request: Request,
        fp: Any,
        code: int,
        message: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        target = urljoin(request.full_url, newurl)
        validate_public_https_url(target)
        return super().redirect_request(request, fp, code, message, headers, target)


def _read_https_response(
    url: str,
    timeout_seconds: float,
    max_response_bytes: int,
    max_redirects: int,
) -> FetchResponse:
    validate_public_https_url(url)
    opener = build_opener(
        ProxyHandler({}),
        _PublicHTTPSHandler(),
        _SafeRedirectHandler(),
    )
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,text/plain",
            "User-Agent": "ResearchIntelligenceAgent/0.1 (+public research fetch)",
        },
        method="GET",
    )
    # urllib's handler has a fixed redirect ceiling; this argument remains part of
    # the transport contract for injectable transports and future urllib updates.
    if max_redirects != URL_FETCH_MAX_REDIRECTS:
        raise ValueError("redirect limit differs from the configured policy")
    with opener.open(request, timeout=timeout_seconds) as response:
        length_header = response.headers.get("Content-Length")
        if length_header is not None:
            try:
                content_length = int(length_header)
            except ValueError:
                content_length = None
            if content_length is not None and content_length > max_response_bytes:
                raise ResponseTooLarge("response exceeds configured byte limit")
        body = response.read(max_response_bytes + 1)
        if len(body) > max_response_bytes:
            raise ResponseTooLarge("response exceeds configured byte limit")
        return FetchResponse(
            status_code=response.status,
            content_type=response.headers.get_content_type().lower(),
            charset=response.headers.get_content_charset(),
            final_url=response.geturl(),
            body=body,
        )


class _ReadablePageParser(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self.title_open = False
        self.skip_depth = 0
        self.published_at: datetime | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs}
        if tag in self._SKIP_TAGS:
            self.skip_depth += 1
        if tag == "title":
            self.title_open = True
        if tag == "meta":
            name = (attributes.get("property") or attributes.get("name") or "").lower()
            if name in {"article:published_time", "datepublished", "date"}:
                self.published_at = _parse_datetime(attributes.get("content"))
        if tag == "time" and attributes.get("datetime"):
            self.published_at = self.published_at or _parse_datetime(attributes["datetime"])
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "section"}:
            self.text_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self.title_open = False
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "section"}:
            self.text_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.title_open:
            self.title_parts.append(data)
        else:
            self.text_parts.append(data)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_page(response: FetchResponse) -> FetchedPage:
    if response.status_code != 200:
        raise HTTPError(
            response.final_url,
            response.status_code,
            "page request returned a non-success status",
            None,
            None,
        )
    if response.content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
        raise InvalidPageResponse("unsupported page content type")
    encoding = response.charset or "utf-8"
    try:
        source = response.body.decode(encoding, errors="replace")
    except LookupError:
        source = response.body.decode("utf-8", errors="replace")
    host = urlsplit(response.final_url).hostname or "Public source"
    if response.content_type == "text/plain":
        title = host
        text = source
        published_at = None
    else:
        parser = _ReadablePageParser()
        parser.feed(source)
        parser.close()
        title = " ".join(" ".join(parser.title_parts).split()) or host
        text = " ".join(" ".join(parser.text_parts).split())
        published_at = parser.published_at
    truncated = len(text) > URL_FETCH_MAX_TEXT_CHARS
    extracted = text[:URL_FETCH_MAX_TEXT_CHARS]
    if not extracted.strip():
        raise InvalidPageResponse("page contained no extractable text")
    return FetchedPage(
        final_url=response.final_url,
        status=response.status_code,
        title=title[:1_000],
        publisher=host,
        published_at=published_at,
        extracted_text=extracted,
        retrieved_at=datetime.now(timezone.utc),
        truncated=truncated,
    )


class URLFetchTool:
    name = ToolName.URL_FETCH
    description = "Fetch bounded text from one public HTTPS page."
    input_schema = URLFetchInput
    output_schema = FetchedPage
    timeout_seconds = URL_FETCH_TIMEOUT_SECONDS

    def __init__(
        self,
        *,
        transport: Callable[[str, float, int, int], FetchResponse] | None = None,
        url_validator: Callable[[str], str] = validate_public_https_url,
    ) -> None:
        self._transport = transport or _read_https_response
        self._url_validator = url_validator

    def execute(self, call: ToolCall) -> ToolResult:
        started_at = datetime.now(timezone.utc)
        try:
            fetch_input = URLFetchInput.model_validate(call.arguments.model_dump())
            self._url_validator(fetch_input.url)
            response = self._transport(
                fetch_input.url,
                self.timeout_seconds,
                URL_FETCH_MAX_RESPONSE_BYTES,
                URL_FETCH_MAX_REDIRECTS,
            )
            if len(response.body) > URL_FETCH_MAX_RESPONSE_BYTES:
                raise ResponseTooLarge("response exceeds configured byte limit")
            self._url_validator(response.final_url)
            page = _normalize_page(response)
            page = FetchedPage.model_validate(page.model_dump())
            return ToolResult(
                call_id=call.call_id,
                status=ToolResultStatus.SUCCEEDED,
                output=page,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        except UnsafeDestination:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.UNSAFE_URL,
                retryability=Retryability.NON_RETRYABLE,
                message="Fetch URL or redirect is not a permitted public destination.",
                started_at=started_at,
            )
        except ResponseTooLarge:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_RESPONSE,
                retryability=Retryability.NON_RETRYABLE,
                message="Fetched page exceeded the configured size limit.",
                started_at=started_at,
            )
        except InvalidPageResponse:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_RESPONSE,
                retryability=Retryability.NON_RETRYABLE,
                message="Page response was not usable HTML or plain text.",
                started_at=started_at,
            )
        except (ValidationError, ValueError):
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_ARGUMENT,
                retryability=Retryability.NON_RETRYABLE,
                message="Fetch arguments or response content failed validation.",
                started_at=started_at,
            )
        except HTTPError as error:
            if error.code == 404:
                category, retryability = FailureCategory.NOT_FOUND, Retryability.NON_RETRYABLE
            elif error.code == 429:
                category, retryability = FailureCategory.RATE_LIMIT, Retryability.RETRYABLE
            elif 500 <= error.code < 600:
                category, retryability = FailureCategory.SERVER_ERROR, Retryability.RETRYABLE
            else:
                category, retryability = FailureCategory.INVALID_RESPONSE, Retryability.NON_RETRYABLE
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=category,
                retryability=retryability,
                message=f"Page server returned HTTP {error.code}.",
                started_at=started_at,
            )
        except (TimeoutError, URLError, socket.timeout):
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.TIMEOUT,
                retryability=Retryability.RETRYABLE,
                message="Page request timed out or could not connect.",
                started_at=started_at,
            )
        except Exception:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_RESPONSE,
                retryability=Retryability.NON_RETRYABLE,
                message="Page fetch failed unexpectedly; response details were omitted.",
                started_at=started_at,
            )
