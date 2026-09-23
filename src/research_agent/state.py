"""Run-local state schema; transition behavior belongs to a later phase."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from research_agent.models import (
    ExecutionEvent,
    Failure,
    Goal,
    Plan,
    RecoveryAction,
    RunState,
    StepStatus,
    StrictModel,
    ToolCall,
)


class AgentState(StrictModel):
    run_id: UUID
    lifecycle_state: RunState = RunState.RECEIVED
    goal: Goal
    active_plan: Plan | None = None
    step_statuses: dict[str, StepStatus] = Field(default_factory=dict)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    events: list[ExecutionEvent] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    failures: list[Failure] = Field(default_factory=list)
    recovery_history: list[RecoveryAction] = Field(default_factory=list)

    @classmethod
    def for_goal(cls, goal: Goal, run_id: UUID) -> AgentState:
        return cls(run_id=run_id, goal=goal)
