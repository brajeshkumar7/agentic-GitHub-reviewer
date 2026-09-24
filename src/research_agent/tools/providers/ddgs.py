"""DDGS-backed public search adapter with normalized, bounded results."""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from typing import Any, Callable
from urllib.parse import urlsplit

from pydantic import ValidationError

from research_agent.limits import SEARCH_MAX_RESPONSE_BYTES, SEARCH_TIMEOUT_SECONDS
from research_agent.models import SearchResult, SearchResults, WebSearchInput


class DDGSSearchError(RuntimeError):
    """Safe provider failure category; never includes external response text."""

    def __init__(self, category: str, *, retryable: bool) -> None:
        self.category = category
        self.retryable = retryable
        super().__init__(f"DDGS search failed ({category})")


class DDGSSearchProvider:
    """Search through DDGS' DuckDuckGo backend without API credentials."""

    def __init__(
        self,
        search: Callable[..., list[dict[str, Any]]] | None = None,
    ) -> None:
        self._search = search

    def search(self, search_input: WebSearchInput) -> SearchResults:
        time_limit = self._date_limit(search_input)
        try:
            raw_results = self._run_search(
                search_input.query,
                search_input.max_results,
                time_limit,
            )
        except DDGSSearchError:
            raise
        except Exception as error:
            category, retryable = self._classify_error(error)
            raise DDGSSearchError(category, retryable=retryable) from None

        if not isinstance(raw_results, list):
            raise DDGSSearchError("invalid_response", retryable=False)
        try:
            normalized = [
                self._normalize_result(item)
                for item in raw_results[: search_input.max_results]
            ]
            approximate_bytes = sum(
                len(result.title.encode("utf-8"))
                + len(result.url.encode("utf-8"))
                + len(result.snippet.encode("utf-8"))
                for result in normalized
            )
            if approximate_bytes > SEARCH_MAX_RESPONSE_BYTES:
                raise DDGSSearchError("oversized_response", retryable=False)
            return SearchResults(
                results=normalized,
                provider_metadata={"provider": "ddgs", "backend": "duckduckgo"},
            )
        except DDGSSearchError:
            raise
        except (TypeError, ValueError, ValidationError):
            raise DDGSSearchError("invalid_response", retryable=False) from None

    def _run_search(
        self,
        query: str,
        max_results: int,
        time_limit: str | None,
    ) -> list[dict[str, Any]]:
        if self._search is not None:
            return self._search(
                query=query,
                max_results=max_results,
                backend="duckduckgo",
                timelimit=time_limit,
            )
        from ddgs import DDGS

        return DDGS(timeout=SEARCH_TIMEOUT_SECONDS).text(
            query=query,
            max_results=max_results,
            backend="duckduckgo",
            timelimit=time_limit,
        )

    @staticmethod
    def _date_limit(search_input: WebSearchInput) -> str | None:
        if search_input.start is None or search_input.end is None:
            return None
        days = ceil((search_input.end - search_input.start).total_seconds() / 86_400)
        if days <= 1:
            return "d"
        if days <= 7:
            return "w"
        if days <= 31:
            return "m"
        if days <= 366:
            return "y"
        return None

    @staticmethod
    def _normalize_result(item: Any) -> SearchResult:
        if not isinstance(item, dict):
            raise ValueError("search result is not an object")
        title = item.get("title")
        url = item.get("href") or item.get("url")
        snippet = item.get("body") or item.get("snippet") or ""
        if not isinstance(title, str) or not isinstance(url, str) or not isinstance(snippet, str):
            raise ValueError("required search result fields are missing")
        hostname = urlsplit(url).hostname
        if not hostname:
            raise ValueError("search result URL has no hostname")
        return SearchResult(
            title=title[:500],
            url=url,
            snippet=snippet[:2_000],
            source=hostname[:255],
            published_at=DDGSSearchProvider._parse_timestamp(
                item.get("date") or item.get("published_at")
            ),
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

    @staticmethod
    def _classify_error(error: Exception) -> tuple[str, bool]:
        name = type(error).__name__.lower()
        if isinstance(error, TimeoutError) or "timeout" in name:
            return "timeout", True
        if "ratelimit" in name or "rate_limit" in name:
            return "rate_limited", True
        status_code = getattr(error, "status_code", None)
        if isinstance(status_code, int) and status_code >= 500:
            return "server_error", True
        if isinstance(status_code, int) and status_code == 429:
            return "rate_limited", True
        # Backend/network errors are transient unless validation identifies a bad response.
        return "provider_error", True
