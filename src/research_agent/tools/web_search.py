"""Provider-neutral public web search tool."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from pydantic import ValidationError

from research_agent.config import AgentSettings
from research_agent.limits import SEARCH_TIMEOUT_SECONDS
from research_agent.models import (
    FailureCategory,
    Retryability,
    SearchResults,
    ToolCall,
    ToolName,
    ToolResult,
    ToolResultStatus,
    WebSearchInput,
)
from research_agent.tools.base import failed_tool_result
from research_agent.tools.providers.brave import BraveSearchError, BraveSearchProvider


class SearchProvider(Protocol):
    def search(self, search_input: WebSearchInput) -> SearchResults: ...


class WebSearchTool:
    name = ToolName.WEB_SEARCH
    description = "Search public web pages and return normalized candidate sources."
    input_schema = WebSearchInput
    output_schema = SearchResults
    timeout_seconds = SEARCH_TIMEOUT_SECONDS

    def __init__(
        self,
        provider: SearchProvider | None = None,
        *,
        settings: AgentSettings | None = None,
    ) -> None:
        resolved_settings = settings or AgentSettings.from_env()
        self._provider = provider or BraveSearchProvider(
            resolved_settings.brave_search_api_key
        )

    def execute(self, call: ToolCall) -> ToolResult:
        started_at = datetime.now(timezone.utc)
        try:
            search_input = WebSearchInput.model_validate(call.arguments.model_dump())
            results = self._provider.search(search_input)
            results = SearchResults.model_validate(results.model_dump())
            if not results.results:
                return failed_tool_result(
                    call_id=call.call_id,
                    run_id=call.run_id,
                    step_id=call.step_id,
                    category=FailureCategory.EMPTY_RESULTS,
                    retryability=Retryability.SEMANTIC,
                    message="Search completed without candidate results.",
                    started_at=started_at,
                )
            return ToolResult(
                call_id=call.call_id,
                status=ToolResultStatus.SUCCEEDED,
                output=results,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )
        except ValidationError:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_ARGUMENT,
                retryability=Retryability.NON_RETRYABLE,
                message="Search arguments failed validation.",
                started_at=started_at,
            )
        except BraveSearchError as error:
            category = {
                "missing_configuration": FailureCategory.AUTH_CONFIG,
                "authentication": FailureCategory.AUTH_CONFIG,
                "rate_limited": FailureCategory.RATE_LIMIT,
                "server_error": FailureCategory.SERVER_ERROR,
                "timeout": FailureCategory.TIMEOUT,
                "oversized_response": FailureCategory.INVALID_RESPONSE,
                "invalid_response": FailureCategory.INVALID_RESPONSE,
                "http_error": FailureCategory.INVALID_RESPONSE,
            }.get(error.category, FailureCategory.INVALID_RESPONSE)
            retryability = (
                Retryability.RETRYABLE if error.retryable else Retryability.NON_RETRYABLE
            )
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=category,
                retryability=retryability,
                message=f"Search provider failed ({error.category}).",
                started_at=started_at,
            )
        except Exception:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.INVALID_RESPONSE,
                retryability=Retryability.NON_RETRYABLE,
                message="Search tool failed unexpectedly; response details were omitted.",
                started_at=started_at,
            )
