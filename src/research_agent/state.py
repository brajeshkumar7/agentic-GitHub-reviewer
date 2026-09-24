"""Run-local state and validated lifecycle transitions."""

from __future__ import annotations

from uuid import UUID
from typing import Any

from pydantic import Field

from research_agent.event_logger import sanitize_event
from research_agent.models import (
    EventOutcome,
    ExecutionEvent,
    EventType,
    Failure,
    Goal,
    Plan,
    RecoveryAction,
    RunState,
    StepStatus,
    StrictModel,
    ToolCall,
    ToolName,
    ToolResult,
    utc_now,
)


_ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.RECEIVED: {RunState.PLANNING, RunState.FAILED},
    RunState.PLANNING: {RunState.PLAN_VALIDATION, RunState.RECOVERY, RunState.FAILED},
    RunState.PLAN_VALIDATION: {
        RunState.EXECUTING,
        RunState.RECOVERY,
        RunState.FAILED,
    },
    RunState.EXECUTING: {
        RunState.RECOVERY,
        RunState.SYNTHESIZING,
        RunState.FAILED,
    },
    RunState.RECOVERY: {
        RunState.EXECUTING,
        RunState.SYNTHESIZING,
        RunState.FAILED,
    },
    RunState.SYNTHESIZING: {
        RunState.RECOVERY,
        RunState.COMPLETED,
        RunState.PARTIAL,
        RunState.FAILED,
    },
    RunState.COMPLETED: set(),
    RunState.PARTIAL: set(),
    RunState.FAILED: set(),
}


class AgentState(StrictModel):
    run_id: UUID
    lifecycle_state: RunState = RunState.RECEIVED
    goal: Goal
    active_plan: Plan | None = None
    step_statuses: dict[str, StepStatus] = Field(default_factory=dict)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    events: list[ExecutionEvent] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    failures: list[Failure] = Field(default_factory=list)
    step_failures: dict[str, Failure] = Field(default_factory=dict)
    recovery_history: list[RecoveryAction] = Field(default_factory=list)

    @classmethod
    def for_goal(cls, goal: Goal, run_id: UUID) -> AgentState:
        return cls(run_id=run_id, goal=goal)

    def transition(self, target: RunState, *, summary: str | None = None) -> ExecutionEvent:
        if target not in _ALLOWED_TRANSITIONS[self.lifecycle_state]:
            raise ValueError(
                f"illegal lifecycle transition: {self.lifecycle_state.value} -> {target.value}"
            )
        previous = self.lifecycle_state
        self.lifecycle_state = target
        return self.record_event(
            EventType.STATE_TRANSITION,
            outcome=(
                EventOutcome.FAILED
                if target == RunState.FAILED
                else EventOutcome.COMPLETED
                if target == RunState.COMPLETED
                else EventOutcome.SUCCEEDED
            ),
            summary=summary or f"State changed from {previous.value} to {target.value}.",
        )

    def record_event(
        self,
        event_type: EventType,
        *,
        outcome: EventOutcome,
        summary: str,
        step_id: str | None = None,
        call_id: UUID | None = None,
        tool_name: ToolName | None = None,
        attempt: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionEvent:
        event = sanitize_event(
            ExecutionEvent(
                execution_id=self.run_id,
                run_id=self.run_id,
                sequence=len(self.events) + 1,
                timestamp=utc_now(),
                event_type=event_type,
                state=self.lifecycle_state,
                step_id=step_id,
                call_id=call_id,
                tool_name=tool_name,
                attempt=attempt,
                status=outcome,
                metadata={"summary": summary, **(metadata or {})},
            )
        )
        self.events.append(event)
        return event
