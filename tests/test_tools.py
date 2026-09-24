from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from research_agent.config import AgentSettings
from research_agent.limits import URL_FETCH_MAX_RESPONSE_BYTES
from research_agent.models import (
    CalculatorInput,
    CalculatorOperation,
    FailureCategory,
    SearchResult,
    SearchResults,
    ToolCall,
    ToolCallKind,
    ToolName,
    ToolResultStatus,
    URLFetchInput,
    WebSearchInput,
)
from research_agent.tools.calculator import CalculatorTool, evaluate_expression
from research_agent.tools.providers.ddgs import DDGSSearchError, DDGSSearchProvider
from research_agent.tools.registry import ToolRegistry, UnknownToolError
from research_agent.tools.url_fetch import FetchResponse, URLFetchTool
from research_agent.tools.web_search import WebSearchTool


def make_call(tool_name: ToolName, arguments: Any) -> ToolCall:
    return ToolCall(
        run_id=uuid4(),
        step_id="test-step",
        tool_name=tool_name,
        arguments=arguments,
        attempt=1,
        kind=ToolCallKind.PRIMARY,
        created_at=datetime.now(timezone.utc),
    )


class FakeSearchProvider:
    def __init__(self, results: SearchResults | None = None, error: Exception | None = None):
        self.results = results or SearchResults(
            results=[
                SearchResult(
                    title="RAG report",
                    url="https://example.org/rag",
                    snippet="A report about RAG systems.",
                    source="example.org",
                )
            ]
        )
        self.error = error

    def search(self, search_input: WebSearchInput) -> SearchResults:
        assert search_input.max_results > 0
        if self.error is not None:
            raise self.error
        return self.results


def test_registry_registers_tools_and_exposes_validated_metadata() -> None:
    registry = ToolRegistry(
        [
            WebSearchTool(FakeSearchProvider()),
            URLFetchTool(transport=lambda *_: FetchResponse(200, "text/plain", "utf-8", "https://example.org", b"ok"), url_validator=lambda url: url),
            CalculatorTool(),
        ]
    )

    assert registry.get("calculator").name is ToolName.CALCULATOR
    metadata = registry.metadata()
    assert [item.name for item in metadata] == list(ToolName)
    assert all(item.input_schema and item.output_schema for item in metadata)
    assert all(item.timeout_seconds > 0 for item in metadata)


def test_registry_returns_structured_search_success() -> None:
    registry = ToolRegistry([WebSearchTool(FakeSearchProvider())])
    call = make_call(
        ToolName.WEB_SEARCH,
        WebSearchInput(query="RAG research", max_results=5),
    )

    result = registry.dispatch(call)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert isinstance(result.output, SearchResults)
    assert result.output.results[0].source == "example.org"


def test_registry_rejects_unknown_tool_and_invalid_arguments() -> None:
    registry = ToolRegistry([WebSearchTool(FakeSearchProvider())])
    with pytest.raises(UnknownToolError):
        registry.get("shell")
    original = make_call(
        ToolName.WEB_SEARCH,
        WebSearchInput(query="RAG research", max_results=2),
    )
    forged_unknown = original.model_copy(update={"tool_name": "shell"})
    unknown_result = registry.dispatch(forged_unknown)
    assert unknown_result.status is ToolResultStatus.FAILED
    assert unknown_result.failure is not None

    forged_arguments = original.model_copy(
        update={"arguments": URLFetchInput(url="https://example.org")}
    )
    invalid_result = registry.dispatch(forged_arguments)
    assert invalid_result.status is ToolResultStatus.FAILED
    assert invalid_result.failure is not None
    assert invalid_result.failure.category is FailureCategory.INVALID_ARGUMENT


def test_empty_search_is_a_typed_failure() -> None:
    tool = WebSearchTool(FakeSearchProvider(results=SearchResults(results=[])))

    result = tool.execute(
        make_call(ToolName.WEB_SEARCH, WebSearchInput(query="no results", max_results=3))
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.category is FailureCategory.EMPTY_RESULTS


def test_ddgs_provider_normalizes_results_and_applies_bounds() -> None:
    calls: dict[str, Any] = {}

    def fake_search(**kwargs: Any) -> list[dict[str, str]]:
        calls.update(kwargs)
        return [
            {
                "title": "RAG results",
                "href": "https://example.org/rag",
                "body": "A useful discovery snippet.",
                "date": "2026-09-22T12:30:00Z",
            }
        ]

    provider = DDGSSearchProvider(search=fake_search)
    results = provider.search(WebSearchInput(query="RAG", max_results=4))

    assert results.provider_metadata == {"provider": "ddgs", "backend": "duckduckgo"}
    assert results.results[0].source == "example.org"
    assert results.results[0].published_at is not None
    assert calls == {
        "query": "RAG",
        "max_results": 4,
        "backend": "duckduckgo",
        "timelimit": None,
    }


def test_ddgs_provider_maps_requested_date_window_to_backend_filter() -> None:
    captured: dict[str, Any] = {}

    def fake_search(**kwargs: Any) -> list[dict[str, str]]:
        captured.update(kwargs)
        return []

    DDGSSearchProvider(search=fake_search).search(
        WebSearchInput(
            query="RAG",
            max_results=2,
            start=datetime(2026, 9, 17, tzinfo=timezone.utc),
            end=datetime(2026, 9, 24, tzinfo=timezone.utc),
        )
    )

    assert captured["query"] == "RAG"
    assert captured["timelimit"] == "w"


def test_ddgs_provider_malformed_response_becomes_normalized_tool_failure() -> None:
    tool = WebSearchTool(
        provider=DDGSSearchProvider(search=lambda **_kwargs: [{"title": "missing URL"}])
    )

    result = tool.execute(
        make_call(ToolName.WEB_SEARCH, WebSearchInput(query="topic", max_results=2))
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.category is FailureCategory.INVALID_RESPONSE


def test_ddgs_timeout_and_rate_limit_failures_are_typed() -> None:
    timeout_tool = WebSearchTool(
        provider=DDGSSearchProvider(
            search=lambda **_kwargs: (_ for _ in ()).throw(TimeoutError())
        )
    )
    timeout_result = timeout_tool.execute(
        make_call(ToolName.WEB_SEARCH, WebSearchInput(query="topic", max_results=1))
    )
    assert timeout_result.failure is not None
    assert timeout_result.failure.category is FailureCategory.TIMEOUT

    class RatelimitException(Exception):
        pass

    rate_limited = DDGSSearchProvider(
        search=lambda **_kwargs: (_ for _ in ()).throw(RatelimitException())
    )
    with pytest.raises(DDGSSearchError) as failure:
        rate_limited.search(WebSearchInput(query="topic", max_results=1))
    assert failure.value.category == "rate_limited"
    assert failure.value.retryable


def test_url_fetch_normalizes_html_and_truncates_extracted_text() -> None:
    body = (
        b"<html><head><title>Research page</title>"
        b'<meta property="article:published_time" content="2026-09-20T00:00:00Z">'
        b"</head><body><script>ignored()</script><p>Useful research content.</p></body></html>"
    )
    tool = URLFetchTool(
        transport=lambda *_args: FetchResponse(
            200, "text/html", "utf-8", "https://example.org/research", body
        ),
        url_validator=lambda url: url,
    )
    result = tool.execute(
        make_call(ToolName.URL_FETCH, URLFetchInput(url="https://example.org/research"))
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output is not None
    assert result.output.title == "Research page"
    assert result.output.status == 200
    assert "ignored" not in result.output.extracted_text
    assert result.output.published_at is not None


def test_url_fetch_normalizes_timeout_http_and_oversize_failures() -> None:
    call = make_call(ToolName.URL_FETCH, URLFetchInput(url="https://example.org/page"))
    timeout_tool = URLFetchTool(
        transport=lambda *_args: (_ for _ in ()).throw(TimeoutError()),
        url_validator=lambda url: url,
    )
    timeout_result = timeout_tool.execute(call)
    assert timeout_result.failure is not None
    assert timeout_result.failure.category is FailureCategory.TIMEOUT

    http_tool = URLFetchTool(
        transport=lambda *_args: (_ for _ in ()).throw(
            HTTPError("https://example.org/page", 404, "not found", {}, None)
        ),
        url_validator=lambda url: url,
    )
    http_result = http_tool.execute(call)
    assert http_result.failure is not None
    assert http_result.failure.category is FailureCategory.NOT_FOUND

    oversized_tool = URLFetchTool(
        transport=lambda *_args: FetchResponse(
            200,
            "text/plain",
            "utf-8",
            "https://example.org/page",
            b"x" * (URL_FETCH_MAX_RESPONSE_BYTES + 1),
        ),
        url_validator=lambda url: url,
    )
    oversized_result = oversized_tool.execute(call)
    assert oversized_result.failure is not None
    assert oversized_result.failure.category is FailureCategory.INVALID_RESPONSE


def test_url_fetch_rejects_local_file_url_and_private_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ToolCall.model_construct(
        call_id=uuid4(),
        run_id=uuid4(),
        step_id="fetch",
        tool_name=ToolName.URL_FETCH,
        arguments=URLFetchInput.model_construct(url="file:///etc/passwd"),
        attempt=1,
        kind=ToolCallKind.PRIMARY,
        created_at=datetime.now(timezone.utc),
    )
    result = URLFetchTool().execute(call)
    assert result.status is ToolResultStatus.FAILED
    assert result.failure is not None

    import research_agent.tools.safe_url as safe_url

    monkeypatch.setattr(
        safe_url.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    private_call = make_call(
        ToolName.URL_FETCH,
        URLFetchInput(url="https://internal.example/page"),
    )
    private_result = URLFetchTool().execute(private_call)
    assert private_result.failure is not None
    assert private_result.failure.category is FailureCategory.UNSAFE_URL


@pytest.mark.parametrize(
    "expression",
    ["__import__('os').system('whoami')", "2 ** 10", "open('/etc/passwd')", "2 / 0"],
)
def test_calculator_rejects_invalid_or_unsafe_expression(expression: str) -> None:
    call = make_call(ToolName.CALCULATOR, CalculatorInput(expression=expression))

    result = CalculatorTool().execute(call)

    assert result.status is ToolResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.category is FailureCategory.CALCULATOR_ERROR


def test_calculator_evaluates_decimal_subset_and_allowlisted_operations() -> None:
    expression_result = evaluate_expression("(1.5 + 2) * -4 / 2")
    assert expression_result == Decimal("-7.0")

    operation_call = make_call(
        ToolName.CALCULATOR,
        CalculatorInput(
            operation=CalculatorOperation.MEAN,
            operands=[Decimal("1"), Decimal("2"), Decimal("3")],
        ),
    )
    result = CalculatorTool().execute(operation_call)
    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output is not None
    assert result.output.result == Decimal("2")
