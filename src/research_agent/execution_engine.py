"""Deterministic, sequential executor for validated plans."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from research_agent.event_logger import EventLogger
from research_agent.interfaces import ToolRegistry
from research_agent.limits import MAX_EXECUTION_STEPS, MAX_TOOL_ATTEMPTS
from research_agent.models import (
    EventOutcome,
    EventType,
    Failure,
    FailureCategory,
    FailureOrigin,
    Plan,
    RecoveryAction,
    RecoveryKind,
    RecoveryReason,
    Retryability,
    RunState,
    StepStatus,
    ToolCall,
    ToolCallKind,
    ToolName,
    ToolResult,
    ToolResultStatus,
    ValidatedPlan,
    utc_now,
)
from research_agent.state import AgentState
from research_agent.tools.base import failed_tool_result


class ExecutionEngine:
    """Execute a validated plan without delegating control flow to the LLM."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        event_logger: EventLogger | None = None,
    ) -> None:
        self._registry = registry
        self._event_logger = event_logger or EventLogger()

    def execute(self, validated_plan: ValidatedPlan, state: AgentState) -> AgentState:
        """Run steps in stable dependency order and return ready for synthesis."""
        if state.lifecycle_state in {RunState.COMPLETED, RunState.PARTIAL, RunState.FAILED}:
            raise ValueError("cannot execute a plan for a terminal run")

        plan: Plan | None = None
        try:
            if state.lifecycle_state != RunState.PLAN_VALIDATION:
                raise ValueError("execution requires PLAN_VALIDATION state")
            plan = Plan.model_validate(validated_plan.plan.model_dump())
            if plan.goal_id != state.goal.goal_id:
                raise ValueError("validated plan does not belong to this run's goal")
            if state.active_plan is not None and state.active_plan.plan_id != plan.plan_id:
                raise ValueError("agent state already contains a different active plan")
            state.active_plan = plan
            state.step_statuses = {step.id: StepStatus.PENDING for step in plan.steps}
            state.retry_counts = {step.id: 0 for step in plan.steps}
            self._validate_registry_contract(plan)
        except (ValidationError, LookupError, TypeError, ValueError) as error:
            if (
                plan is not None
                and plan.goal_id == state.goal.goal_id
                and (
                    state.active_plan is None
                    or state.active_plan.plan_id == plan.plan_id
                )
            ):
                state.active_plan = plan
                state.step_statuses = {
                    step.id: StepStatus.FAILED for step in plan.steps
                }
                state.retry_counts = {step.id: 0 for step in plan.steps}
            self._fail_run(state, f"Plan execution precondition failed ({type(error).__name__}).")
            return state

        assert plan is not None
        self._emit(
            state,
            EventType.PLAN_VALIDATED,
            EventOutcome.SUCCEEDED,
            "Validated plan accepted by the execution engine.",
        )
        self._transition(state, RunState.EXECUTING)

        ordered_steps = self._topological_order(plan)
        for index, step in enumerate(ordered_steps):
            if len(state.tool_calls) >= MAX_EXECUTION_STEPS:
                self._skip_remaining(
                    state,
                    ordered_steps[index:],
                    "Run-wide tool-call limit was reached.",
                )
                break

            failed_dependencies = [
                dependency
                for dependency in step.dependencies
                if state.step_statuses[dependency]
                in {StepStatus.FAILED, StepStatus.SKIPPED}
            ]
            if failed_dependencies:
                self._mark_skipped(
                    state,
                    step.id,
                    "Step skipped because prerequisite(s) did not succeed: "
                    + ", ".join(failed_dependencies),
                )
                continue

            if any(
                state.step_statuses[dependency] != StepStatus.SUCCEEDED
                for dependency in step.dependencies
            ):
                self._mark_skipped(
                    state,
                    step.id,
                    "Step skipped because a prerequisite did not complete.",
                )
                continue

            state.step_statuses[step.id] = StepStatus.RUNNING
            self._emit(
                state,
                EventType.STEP_STARTED,
                EventOutcome.STARTED,
                step.objective,
                step_id=step.id,
                tool_name=step.tool_name,
            )
            self._execute_step(state, step.id, step.tool_name, step.input)

        self._transition(
            state,
            RunState.SYNTHESIZING,
            summary="Execution finished; run is ready for report synthesis.",
        )
        return state

    def _execute_step(
        self,
        state: AgentState,
        step_id: str,
        tool_name: ToolName,
        arguments: BaseModel,
    ) -> None:
        attempt = 1
        while attempt <= MAX_TOOL_ATTEMPTS:
            if len(state.tool_calls) >= MAX_EXECUTION_STEPS:
                failure = self._make_failure(
                    state,
                    step_id,
                    FailureCategory.RETRY_EXHAUSTED,
                    Retryability.NON_RETRYABLE,
                    "Run-wide tool-call limit was reached.",
                )
                self._record_permanent_failure(
                    state, step_id, tool_name, failure, attempt
                )
                return

            try:
                tool = self._registry.get(tool_name.value)
                validated_arguments = self._registry.validate_arguments(
                    tool_name.value, arguments
                )
                if not isinstance(validated_arguments, tool.input_schema):
                    raise ValueError("tool input schema mismatch")
            except Exception as error:
                failure = self._make_failure(
                    state,
                    step_id,
                    FailureCategory.INVALID_ARGUMENT,
                    Retryability.NON_RETRYABLE,
                    f"Tool arguments or registry lookup failed ({type(error).__name__}).",
                )
                self._record_permanent_failure(
                    state, step_id, tool_name, failure, attempt
                )
                return

            call = ToolCall(
                run_id=state.run_id,
                step_id=step_id,
                tool_name=tool_name,
                arguments=validated_arguments,
                attempt=attempt,
                kind=ToolCallKind.PRIMARY if attempt == 1 else ToolCallKind.RETRY,
                created_at=utc_now(),
            )
            state.tool_calls.append(call)
            self._emit(
                state,
                EventType.TOOL_CALL_STARTED,
                EventOutcome.STARTED,
                f"Dispatching registered tool {tool_name.value}.",
                step_id=step_id,
                call_id=call.call_id,
                tool_name=tool_name,
                attempt=attempt,
            )

            result = self._dispatch_and_validate(call, tool)
            state.tool_results.append(result)
            if result.status == ToolResultStatus.SUCCEEDED:
                state.step_statuses[step_id] = StepStatus.SUCCEEDED
                self._emit(
                    state,
                    EventType.TOOL_CALL_SUCCEEDED,
                    EventOutcome.SUCCEEDED,
                    "Tool returned a validated result.",
                    step_id=step_id,
                    call_id=call.call_id,
                    tool_name=tool_name,
                    attempt=attempt,
                )
                self._emit(
                    state,
                    EventType.STEP_COMPLETED,
                    EventOutcome.SUCCEEDED,
                    "Step completed successfully.",
                    step_id=step_id,
                    tool_name=tool_name,
                    attempt=attempt,
                )
                return

            failure = result.failure
            if failure is None:
                failure = self._make_failure(
                    state,
                    step_id,
                    FailureCategory.INVALID_RESPONSE,
                    Retryability.NON_RETRYABLE,
                    "Tool returned a failure result without failure details.",
                    call_id=call.call_id,
                )
            state.failures.append(failure)
            self._emit(
                state,
                EventType.TOOL_CALL_FAILED,
                EventOutcome.FAILED,
                f"Tool call failed ({failure.category.value}).",
                step_id=step_id,
                call_id=call.call_id,
                tool_name=tool_name,
                attempt=attempt,
            )

            can_retry = (
                failure.retryability == Retryability.RETRYABLE
                and attempt < MAX_TOOL_ATTEMPTS
                and len(state.tool_calls) < MAX_EXECUTION_STEPS
            )
            if can_retry:
                self._transition(state, RunState.RECOVERY)
                state.retry_counts[step_id] = attempt
                state.recovery_history.append(
                    RecoveryAction(
                        failure_id=failure.failure_id,
                        kind=RecoveryKind.RETRY,
                        target_step_id=step_id,
                        reason_code=RecoveryReason.TRANSIENT,
                        selected_at=utc_now(),
                    )
                )
                self._emit(
                    state,
                    EventType.RETRY_SCHEDULED,
                    EventOutcome.SCHEDULED,
                    "Transient failure will be retried once within the attempt limit.",
                    step_id=step_id,
                    tool_name=tool_name,
                    attempt=attempt + 1,
                )
                self._emit(
                    state,
                    EventType.RECOVERY_APPLIED,
                    EventOutcome.RECOVERED,
                    "Scheduled one bounded retry.",
                    step_id=step_id,
                    tool_name=tool_name,
                    attempt=attempt + 1,
                )
                self._transition(state, RunState.EXECUTING)
                attempt += 1
                continue

            self._record_permanent_failure(
                state,
                step_id,
                tool_name,
                failure,
                attempt,
                failure_event_recorded=True,
            )
            return

    def _dispatch_and_validate(self, call: ToolCall, tool: Any) -> ToolResult:
        try:
            raw_result = self._registry.dispatch(call)
            result = ToolResult.model_validate(
                raw_result.model_dump() if isinstance(raw_result, ToolResult) else raw_result
            )
            if result.call_id != call.call_id:
                raise ValueError("tool result call ID did not match request")
            if result.status == ToolResultStatus.SUCCEEDED:
                if result.output is None:
                    raise ValueError("successful tool result has no output")
                output = tool.output_schema.model_validate(result.output.model_dump())
                result = result.model_copy(update={"output": output})
            elif (
                result.failure is None
                or result.failure.run_id != call.run_id
                or result.failure.call_id != call.call_id
                or result.failure.step_id != call.step_id
            ):
                raise ValueError("failed tool result has invalid failure provenance")
            return result
        except TimeoutError:
            return self._failure_result(
                call,
                FailureCategory.TIMEOUT,
                Retryability.RETRYABLE,
                "Tool execution timed out.",
            )
        except Exception as error:
            return self._failure_result(
                call,
                FailureCategory.INVALID_RESPONSE,
                Retryability.NON_RETRYABLE,
                f"Tool result failed validation ({type(error).__name__}).",
            )

    def _failure_result(
        self,
        call: ToolCall,
        category: FailureCategory,
        retryability: Retryability,
        message: str,
    ) -> ToolResult:
        return failed_tool_result(
            call_id=call.call_id,
            run_id=call.run_id,
            step_id=call.step_id,
            category=category,
            retryability=retryability,
            message=message,
            started_at=datetime.now(timezone.utc),
        )

    def _record_permanent_failure(
        self,
        state: AgentState,
        step_id: str,
        tool_name: ToolName,
        failure: Failure,
        attempt: int,
        *,
        failure_event_recorded: bool = False,
    ) -> None:
        state.step_statuses[step_id] = StepStatus.FAILED
        state.step_failures[step_id] = failure
        if failure not in state.failures:
            state.failures.append(failure)
        if not failure_event_recorded:
            self._emit(
                state,
                EventType.TOOL_CALL_FAILED,
                EventOutcome.FAILED,
                f"Step failed before or during dispatch ({failure.category.value}).",
                step_id=step_id,
                tool_name=tool_name,
                attempt=attempt if attempt <= MAX_TOOL_ATTEMPTS else None,
            )
        self._transition(state, RunState.RECOVERY)
        state.recovery_history.append(
            RecoveryAction(
                failure_id=failure.failure_id,
                kind=RecoveryKind.MARK_FAILED,
                target_step_id=step_id,
                reason_code=(
                    RecoveryReason.BUDGET_EXHAUSTED
                    if failure.category == FailureCategory.RETRY_EXHAUSTED
                    or attempt >= MAX_TOOL_ATTEMPTS
                    or len(state.tool_calls) >= MAX_EXECUTION_STEPS
                    else RecoveryReason.PERMANENT_ERROR
                ),
                selected_at=utc_now(),
            )
        )
        self._emit(
            state,
            EventType.RECOVERY_APPLIED,
            EventOutcome.FAILED,
            "Step marked failed; dependent steps will be skipped.",
            step_id=step_id,
            tool_name=tool_name,
            attempt=attempt if attempt <= MAX_TOOL_ATTEMPTS else None,
        )
        self._transition(state, RunState.EXECUTING)

    def _make_failure(
        self,
        state: AgentState,
        step_id: str,
        category: FailureCategory,
        retryability: Retryability,
        message: str,
        *,
        call_id: UUID | None = None,
    ) -> Failure:
        failure = Failure(
            category=category,
            origin=FailureOrigin.EXECUTOR,
            retryability=retryability,
            run_id=state.run_id,
            step_id=step_id,
            call_id=call_id,
            message=message,
            occurred_at=utc_now(),
        )
        return failure

    def _validate_registry_contract(self, plan: Plan) -> None:
        registered_names = {metadata.name for metadata in self._registry.metadata()}
        for step in plan.steps:
            if step.tool_name not in registered_names:
                raise LookupError(f"tool is not registered: {step.tool_name.value}")
            self._registry.validate_arguments(step.tool_name.value, step.input)
            if step.fallback is not None:
                if step.fallback.tool_name not in registered_names:
                    raise LookupError(
                        f"fallback tool is not registered: {step.fallback.tool_name.value}"
                    )
                self._registry.validate_arguments(
                    step.fallback.tool_name.value, step.fallback.arguments
                )

    @staticmethod
    def _topological_order(plan: Plan) -> list[Any]:
        remaining = list(plan.steps)
        ordered: list[Any] = []
        ordered_ids: set[str] = set()
        while remaining:
            ready_index = next(
                (
                    index
                    for index, step in enumerate(remaining)
                    if set(step.dependencies) <= ordered_ids
                ),
                None,
            )
            if ready_index is None:
                raise ValueError("plan contains unresolved or circular dependencies")
            step = remaining.pop(ready_index)
            ordered.append(step)
            ordered_ids.add(step.id)
        return ordered

    def _skip_remaining(
        self, state: AgentState, steps: list[Any], reason: str
    ) -> None:
        for step in steps:
            if state.step_statuses.get(step.id) == StepStatus.PENDING:
                self._mark_skipped(state, step.id, reason)

    def _mark_skipped(self, state: AgentState, step_id: str, reason: str) -> None:
        state.step_statuses[step_id] = StepStatus.SKIPPED
        self._emit(
            state,
            EventType.STEP_SKIPPED,
            EventOutcome.SKIPPED,
            reason,
            step_id=step_id,
        )

    def _fail_run(self, state: AgentState, message: str) -> None:
        failure = Failure(
            category=FailureCategory.STATE_INVARIANT,
            origin=FailureOrigin.EXECUTOR,
            retryability=Retryability.NON_RETRYABLE,
            run_id=state.run_id,
            message=message,
            occurred_at=utc_now(),
        )
        state.failures.append(failure)
        if self._can_transition_to_failed(state):
            self._transition(state, RunState.FAILED, summary=message)
        else:
            raise ValueError("run cannot enter FAILED from its current terminal state")

    @staticmethod
    def _can_transition_to_failed(state: AgentState) -> bool:
        return state.lifecycle_state not in {
            RunState.COMPLETED,
            RunState.PARTIAL,
            RunState.FAILED,
        }

    def _emit(
        self,
        state: AgentState,
        event_type: EventType,
        outcome: EventOutcome,
        summary: str,
        *,
        step_id: str | None = None,
        call_id: UUID | None = None,
        tool_name: ToolName | None = None,
        attempt: int | None = None,
    ) -> None:
        event = state.record_event(
            event_type,
            outcome=outcome,
            summary=summary,
            step_id=step_id,
            call_id=call_id,
            tool_name=tool_name,
            attempt=attempt,
        )
        self._event_logger.emit(event)

    def _transition(
        self, state: AgentState, target: RunState, *, summary: str | None = None
    ) -> None:
        event = state.transition(target, summary=summary)
        self._event_logger.emit(event)
