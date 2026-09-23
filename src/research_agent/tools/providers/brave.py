"""Brave Search API transport and normalization adapter."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from pydantic import SecretStr, ValidationError

from research_agent.limits import (
    SEARCH_MAX_RESPONSE_BYTES,
    SEARCH_TIMEOUT_SECONDS,
)
from research_agent.models import SearchResult, SearchResults, WebSearchInput

BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchError(RuntimeError):
    def __init__(self, category: str, *, retryable: bool) -> None:
        self.category = category
        self.retryable = retryable
        super().__init__(f"Brave Search request failed ({category})")


class BraveSearchProvider:
    """Calls one fixed Brave endpoint and returns common normalized models."""

    def __init__(self, api_key: SecretStr | None) -> None:
        self._api_key = api_key

    def search(self, search_input: WebSearchInput) -> SearchResults:
        if self._api_key is None:
            raise BraveSearchError("missing_configuration", retryable=False)
        query: dict[str, str | int] = {
            "q": search_input.query,
            "count": search_input.max_results,
            "search_lang": "en",
        }
        if search_input.start is not None and search_input.end is not None:
            query["freshness"] = (
                f"{search_input.start.date().isoformat()}to"
                f"{search_input.end.date().isoformat()}"
            )
        request = Request(
            f"{BRAVE_SEARCH_ENDPOINT}?{urlencode(query)}",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self._api_key.get_secret_value(),
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=SEARCH_TIMEOUT_SECONDS) as response:
                body = response.read(SEARCH_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            if error.code in {401, 403}:
                category, retryable = "authentication", False
            elif error.code == 429:
                category, retryable = "rate_limited", True
            elif 500 <= error.code < 600:
                category, retryable = "server_error", True
            else:
                category, retryable = "http_error", False
            raise BraveSearchError(category, retryable=retryable) from None
        except (TimeoutError, URLError, OSError):
            raise BraveSearchError("timeout", retryable=True) from None
        if len(body) > SEARCH_MAX_RESPONSE_BYTES:
            raise BraveSearchError("oversized_response", retryable=False)

        try:
            data = json.loads(body)
            raw_results = data["web"]["results"]
            if not isinstance(raw_results, list):
                raise ValueError("results is not an array")
            normalized = [self._normalize_result(item) for item in raw_results]
            return SearchResults(
                results=normalized[: search_input.max_results],
                provider_metadata={"provider": "brave"},
            )
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError, ValidationError):
            raise BraveSearchError("invalid_response", retryable=False) from None

    @staticmethod
    def _normalize_result(item: Any) -> SearchResult:
        if not isinstance(item, dict):
            raise ValueError("search result is not an object")
        title = item.get("title")
        url = item.get("url")
        snippet = item.get("description")
        if not all(isinstance(value, str) for value in (title, url, snippet)):
            raise ValueError("required result fields are missing")
        hostname = urlsplit(url).hostname
        if not hostname:
            raise ValueError("result URL has no hostname")
        timestamp = BraveSearchProvider._parse_timestamp(
            item.get("page_age") or item.get("published_at") or item.get("timestamp")
        )
        return SearchResult(
            title=title[:500],
            url=url,
            snippet=snippet[:2_000],
            source=hostname[:255],
            published_at=timestamp,
        )

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
