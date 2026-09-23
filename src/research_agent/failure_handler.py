"""Deterministic classification and bounded recovery action selection."""

from __future__ import annotations

from research_agent.limits import (
    MAX_EXECUTION_STEPS,
    MAX_RETRIES_PER_STEP,
    MAX_TOOL_ATTEMPTS,
)
from research_agent.models import (
    Failure,
    FailureCategory,
    RecoveryAction,
    RecoveryKind,
    RecoveryReason,
    Retryability,
    ToolCall,
    ToolCallKind,
    utc_now,
)
from research_agent.state import AgentState
from research_agent.models import PlanStep


_TERMINAL_CATEGORIES = {
    FailureCategory.INVALID_ARGUMENT,
    FailureCategory.UNSAFE_URL,
    FailureCategory.AUTH_CONFIG,
    FailureCategory.STATE_INVARIANT,
}
_RECOVERABLE_CATEGORIES = {
    FailureCategory.EMPTY_RESULTS,
    FailureCategory.INSUFFICIENT_EVIDENCE,
    FailureCategory.NOT_FOUND,
}
_TRANSIENT_CATEGORIES = {
    FailureCategory.TIMEOUT,
    FailureCategory.RATE_LIMIT,
    FailureCategory.SERVER_ERROR,
    FailureCategory.LLM_ERROR,
    FailureCategory.INVALID_RESPONSE,
}


class FailureHandler:
    """Choose retry, validated fallback, one replan, or permanent failure."""

    def __init__(self, *, replanning_enabled: bool = False) -> None:
        self._replanning_enabled = replanning_enabled

    def recover(
        self, failure: Failure, state: AgentState, step: PlanStep
    ) -> RecoveryAction:
        """Classify a failure and choose exactly one bounded next action."""
        action: RecoveryKind = RecoveryKind.MARK_FAILED
        reason = RecoveryReason.PERMANENT_ERROR
        latest_call = self._failed_call(failure, state)
        calls_used = self._calls_used_for_step(state, step)
        attempts_remain = (
            calls_used < MAX_TOOL_ATTEMPTS
            and len(state.tool_calls) < MAX_EXECUTION_STEPS
        )
        retries_used = state.retry_counts.get(step.id, 0)

        if failure.category in _TERMINAL_CATEGORIES or failure.origin.value == "validator":
            action = RecoveryKind.MARK_FAILED
            reason = RecoveryReason.PERMANENT_ERROR
        elif (
            failure.retryability == Retryability.RETRYABLE
            and failure.category in _TRANSIENT_CATEGORIES
            and retries_used < MAX_RETRIES_PER_STEP
            and attempts_remain
            and latest_call is not None
        ):
            action = RecoveryKind.RETRY
            reason = RecoveryReason.TRANSIENT
        elif failure.category in _RECOVERABLE_CATEGORIES:
            if (
                step.fallback is not None
                and not self._fallback_already_used(state, step.id)
                and attempts_remain
                and latest_call is not None
            ):
                action = RecoveryKind.FALLBACK
                reason = (
                    RecoveryReason.EMPTY_RESULTS
                    if failure.category == FailureCategory.EMPTY_RESULTS
                    else RecoveryReason.PERMANENT_ERROR
                )
            elif (
                self._replanning_enabled
                and state.active_plan is not None
                and state.active_plan.revision < 2
                and attempts_remain
                and latest_call is not None
            ):
                action = RecoveryKind.REPLAN
                reason = (
                    RecoveryReason.INSUFFICIENT_EVIDENCE
                    if failure.category == FailureCategory.INSUFFICIENT_EVIDENCE
                    else RecoveryReason.EMPTY_RESULTS
                )
            else:
                action = RecoveryKind.MARK_FAILED
                reason = RecoveryReason.BUDGET_EXHAUSTED if not attempts_remain else RecoveryReason.PERMANENT_ERROR
        else:
            action = RecoveryKind.MARK_FAILED
            reason = RecoveryReason.BUDGET_EXHAUSTED if not attempts_remain else RecoveryReason.PERMANENT_ERROR

        replacement_call = None
        if action in {RecoveryKind.RETRY, RecoveryKind.FALLBACK}:
            replacement_call = self._build_recovery_call(
                state=state,
                step=step,
                latest_call=latest_call,
                kind=action,
                next_attempt=calls_used + 1,
            )

        return RecoveryAction(
            failure_id=failure.failure_id,
            kind=action,
            target_step_id=step.id,
            replacement_call=replacement_call,
            reason_code=reason,
            selected_at=utc_now(),
        )

    @staticmethod
    def _failed_call(failure: Failure, state: AgentState) -> ToolCall | None:
        if failure.call_id is None:
            return None
        return next(
            (call for call in reversed(state.tool_calls) if call.call_id == failure.call_id),
            None,
        )

    @staticmethod
    def _calls_used_for_step(state: AgentState, step: PlanStep) -> int:
        logical_step_ids = {step.id}
        if step.recovery_of_step_id:
            logical_step_ids.add(step.recovery_of_step_id)
        return sum(call.step_id in logical_step_ids for call in state.tool_calls)

    @staticmethod
    def _fallback_already_used(state: AgentState, step_id: str) -> bool:
        return any(
            action.target_step_id == step_id and action.kind == RecoveryKind.FALLBACK
            for action in state.recovery_history
        )

    @staticmethod
    def _build_recovery_call(
        *,
        state: AgentState,
        step: PlanStep,
        latest_call: ToolCall | None,
        kind: RecoveryKind,
        next_attempt: int,
    ) -> ToolCall:
        if latest_call is None or next_attempt > MAX_TOOL_ATTEMPTS:
            raise ValueError("recovery call cannot exceed the configured attempt budget")
        if kind == RecoveryKind.FALLBACK:
            if step.fallback is None:
                raise ValueError("fallback recovery requested without a validated fallback")
            tool_name = step.fallback.tool_name
            arguments = step.fallback.arguments
            call_kind = ToolCallKind.FALLBACK
        else:
            tool_name = latest_call.tool_name
            arguments = latest_call.arguments
            call_kind = ToolCallKind.RETRY
        return ToolCall(
            run_id=state.run_id,
            step_id=step.id,
            tool_name=tool_name,
            arguments=arguments,
            attempt=next_attempt,
            kind=call_kind,
            created_at=utc_now(),
        )
