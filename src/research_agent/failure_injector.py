"""Deterministic, one-shot failure injection for recovery demonstrations."""

from __future__ import annotations

from research_agent.config import AgentSettings
from research_agent.models import (
    EventOutcome,
    EventType,
    FailureCategory,
    FailureInjectionMode,
    Retryability,
    ToolCall,
    ToolName,
    ToolResult,
)
from research_agent.tools.base import failed_tool_result
from research_agent.models import utc_now


class FailureInjector:
    """Inject exactly one configured failure and expose it in run events."""

    def __init__(self, settings: AgentSettings) -> None:
        self._mode = settings.agent_failure_mode if settings.agent_inject_failure else None
        self._tool = settings.agent_failure_tool
        self._used = False

    def maybe_fail(self, call: ToolCall) -> ToolResult | None:
        if self._used or self._mode is None:
            return None
        if self._tool is not None and call.tool_name != self._tool:
            return None
        self._used = True
        if self._mode == FailureInjectionMode.TOOL_TIMEOUT:
            category = FailureCategory.TIMEOUT
            message = "Demonstration failure injected: forced tool timeout."
        else:
            category = FailureCategory.INVALID_RESPONSE
            message = "Demonstration failure injected: forced malformed tool response."
        return failed_tool_result(
            call_id=call.call_id,
            run_id=call.run_id,
            step_id=call.step_id,
            category=category,
            retryability=Retryability.RETRYABLE,
            message=message,
            started_at=utc_now(),
        )

    @property
    def pending(self) -> bool:
        return self._mode is not None and not self._used

