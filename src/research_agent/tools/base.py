"""Common, provider-neutral tool interface and safe failure construction."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from research_agent.models import (
    Failure,
    FailureCategory,
    FailureOrigin,
    Retryability,
    StrictModel,
    ToolCall,
    ToolName,
    ToolResult,
    ToolResultStatus,
    utc_now,
)


class Tool(Protocol):
    name: ToolName
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    timeout_seconds: float

    def execute(self, call: ToolCall) -> ToolResult: ...


class ToolMetadata(StrictModel):
    name: ToolName
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    timeout_seconds: float = Field(gt=0)


def failed_tool_result(
    *,
    call_id: UUID,
    run_id: UUID,
    step_id: str,
    category: FailureCategory,
    retryability: Retryability,
    message: str,
    started_at: datetime,
) -> ToolResult:
    """Create a sanitized typed failure; callers provide no remote body text."""

    finished_at = utc_now()
    failure = Failure(
        category=category,
        origin=FailureOrigin.TOOL,
        retryability=retryability,
        run_id=run_id,
        step_id=step_id,
        call_id=call_id,
        message=message,
        occurred_at=finished_at,
    )
    return ToolResult(
        call_id=call_id,
        status=ToolResultStatus.FAILED,
        failure=failure,
        started_at=started_at,
        finished_at=finished_at,
    )
