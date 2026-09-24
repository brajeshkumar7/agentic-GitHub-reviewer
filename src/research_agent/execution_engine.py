"""Deterministic, sequential executor for validated plans."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from research_agent.event_logger import EventLogger
from research_agent.config import AgentSettings
from research_agent.failure_handler import FailureHandler
from research_agent.failure_injector import FailureInjector
from research_agent.interfaces import ToolRegistry
from research_agent.limits import MAX_EXECUTION_STEPS, MAX_TOOL_ATTEMPTS
from research_agent.models import (
    EventOutcome,
    EventType,
    Failure,
    FailureCategory,
    FailureOrigin,
    Plan,
    PlanStep,
    Goal,
    SearchResults,
    SearchResultReference,
    URLFetchInput,
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
from research_agent.plan_validator import PlanValidator
from research_agent.tools.base import failed_tool_result


class ExecutionEngine:
    """Execute a validated plan without delegating control flow to the LLM."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        event_logger: EventLogger | None = None,
        failure_handler: FailureHandler | None = None,
        settings: AgentSettings | None = None,
        replanner: Callable[[Goal, AgentState, Failure], Plan | Failure] | None = None,
        plan_validator: PlanValidator | None = None,
    ) -> None:
        self._registry = registry
        self._event_logger = event_logger or EventLogger()
        self._replanner = replanner
        self._plan_validator = plan_validator or PlanValidator()
        self._failure_handler = failure_handler or FailureHandler(
            replanning_enabled=replanner is not None
        )
        self._failure_injector = FailureInjector(settings or AgentSettings.from_env())

    def execute(self, validated_plan: ValidatedPlan, state: AgentState) -> AgentState:
        """Run steps in stable dependency order and return ready for synthesis."""
        if state.lifecycle_state in {RunState.COMPLETED, RunState.PARTIAL, RunState.FAILED}:
            raise ValueError("cannot execute a plan for a terminal run")

        plan: Plan | None = None
        try:
            plan = Plan.model_validate(validated_plan.plan.model_dump())
            if state.lifecycle_state != RunState.PLAN_VALIDATION:
                raise ValueError("execution requires PLAN_VALIDATION state")
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
                for step in plan.steps:
                    self._emit(
                        state,
                        EventType.STEP_FAILED,
                        EventOutcome.FAILED,
                        "Step was not executed because a plan precondition failed.",
                        step_id=step.id,
                        tool_name=step.tool_name,
                    )
            self._fail_run(
                state,
                f"Plan execution precondition failed ({type(error).__name__}).",
                category=(
                    FailureCategory.INVALID_ARGUMENT
                    if isinstance(error, LookupError)
                    else FailureCategory.STATE_INVARIANT
                ),
            )
            return state

        assert plan is not None
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
            self._execute_step(state, step)
            if state.lifecycle_state == RunState.FAILED:
                return state

        self._transition(
            state,
            RunState.SYNTHESIZING,
            summary="Execution finished; run is ready for report synthesis.",
        )
        return state

    def _execute_step(self, state: AgentState, step: PlanStep) -> None:
        step_id = step.id
        tool_name = step.tool_name
        arguments: BaseModel = step.input
        next_kind = ToolCallKind.PRIMARY
        while True:
            logical_step_ids = {step_id}
            if step.recovery_of_step_id is not None:
                logical_step_ids.add(step.recovery_of_step_id)
            attempt = sum(call.step_id in logical_step_ids for call in state.tool_calls) + 1
            if len(state.tool_calls) >= MAX_EXECUTION_STEPS:
                failure = self._make_failure(
                    state,
                    step_id,
                    FailureCategory.RETRY_EXHAUSTED,
                    Retryability.NON_RETRYABLE,
                    "Run-wide tool-call limit was reached.",
                )
                self._handle_failure(state, step, failure, attempt)
                return

            try:
                tool = self._registry.get(tool_name.value)
                if isinstance(arguments, SearchResultReference):
                    arguments = self._resolve_search_reference(arguments, state)
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
                self._handle_failure(state, step, failure, attempt)
                return

            call = ToolCall(
                run_id=state.run_id,
                step_id=step_id,
                tool_name=tool_name,
                arguments=validated_arguments,
                attempt=attempt,
                kind=next_kind,
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

            injected_result = self._failure_injector.maybe_fail(call)
            if injected_result is not None:
                self._emit(
                    state,
                    EventType.FAILURE_INJECTED,
                    EventOutcome.FAILED,
                    f"Demonstration failure injected ({injected_result.failure.category.value}).",
                    step_id=step_id,
                    call_id=call.call_id,
                    tool_name=tool_name,
                    attempt=attempt,
                )
                result = injected_result
            elif tool_name == ToolName.URL_FETCH and not self._url_is_authorized(
                validated_arguments, state
            ):
                result = self._failure_result(
                    call,
                    FailureCategory.UNSAFE_URL,
                    Retryability.NON_RETRYABLE,
                    "Fetch URL was not present in the goal or a prior validated search result.",
                )
            else:
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

            action = self._handle_failure(state, step, failure, attempt)
            if action is None or action.kind not in {RecoveryKind.RETRY, RecoveryKind.FALLBACK}:
                return
            assert action.replacement_call is not None
            arguments = action.replacement_call.arguments
            tool_name = action.replacement_call.tool_name
            next_kind = action.replacement_call.kind

    def _handle_failure(
        self,
        state: AgentState,
        step: PlanStep,
        failure: Failure,
        attempt: int,
    ) -> RecoveryAction | None:
        if failure.call_id is None:
            self._emit(
                state,
                EventType.TOOL_CALL_FAILED,
                EventOutcome.FAILED,
                f"Step failed before tool dispatch ({failure.category.value}).",
                step_id=step.id,
                tool_name=step.tool_name,
                attempt=attempt if attempt <= MAX_TOOL_ATTEMPTS else None,
            )
        if state.lifecycle_state == RunState.EXECUTING:
            self._transition(state, RunState.RECOVERY)
        self._emit(
            state,
            EventType.RECOVERY_STARTED,
            EventOutcome.STARTED,
            f"Selecting bounded recovery for {failure.category.value}.",
            step_id=step.id,
            tool_name=step.tool_name,
            attempt=attempt,
        )
        action = self._failure_handler.recover(failure, state, step)
        state.recovery_history.append(action)
        if action.kind == RecoveryKind.RETRY:
            state.retry_counts[step.id] = state.retry_counts.get(step.id, 0) + 1
            self._emit(
                state,
                EventType.RETRY_ATTEMPTED,
                EventOutcome.SCHEDULED,
                "A bounded retry was selected.",
                step_id=step.id,
                tool_name=action.replacement_call.tool_name if action.replacement_call else step.tool_name,
                attempt=attempt + 1,
            )
        if action.kind == RecoveryKind.REPLAN:
            self._emit(
                state,
                EventType.REPLAN_STARTED,
                EventOutcome.STARTED,
                "Starting the single permitted validated plan revision.",
                step_id=step.id,
                tool_name=step.tool_name,
            )
            if self._replanner is None:
                self._fail_run(state, "Recovery selected replanning without a configured planner.")
                return None
            try:
                proposal = self._replanner(state.goal, state, failure)
                if isinstance(proposal, Failure):
                    validated = proposal
                else:
                    validated = self._plan_validator.validate(
                        state.goal, proposal, state, self._registry
                    )
            except Exception as error:
                validated = Failure(
                    category=FailureCategory.INVALID_ARGUMENT,
                    origin=FailureOrigin.VALIDATOR,
                    retryability=Retryability.NON_RETRYABLE,
                    run_id=state.run_id,
                    step_id=step.id,
                    message=f"Replanned proposal failed ({type(error).__name__}).",
                    occurred_at=utc_now(),
                )
            if isinstance(validated, Failure):
                state.failures.append(validated)
                state.step_statuses[step.id] = StepStatus.FAILED
                state.step_failures[step.id] = failure
                self._emit(
                    state,
                    EventType.STEP_FAILED,
                    EventOutcome.FAILED,
                    "Step failed because the revised plan did not validate.",
                    step_id=step.id,
                    tool_name=step.tool_name,
                )
                self._emit(
                    state,
                    EventType.PLAN_REJECTED,
                    EventOutcome.REJECTED,
                    "Replanned proposal failed validation.",
                    step_id=step.id,
                    tool_name=step.tool_name,
                )
                self._emit(
                    state,
                    EventType.RECOVERY_APPLIED,
                    EventOutcome.FAILED,
                    "Recovery stopped because the revised plan was invalid.",
                    step_id=step.id,
                    tool_name=step.tool_name,
                )
                self._fail_run(
                    state,
                    "Invalid plan after the single permitted replan.",
                    category=FailureCategory.INVALID_ARGUMENT,
                )
                return None
            revised = validated.plan
            replacement_steps = [
                candidate
                for candidate in revised.steps
                if candidate.recovery_of_step_id == step.id
            ]
            if len(replacement_steps) != 1 or len(revised.steps) != 1:
                self._emit(
                    state,
                    EventType.PLAN_REJECTED,
                    EventOutcome.REJECTED,
                    "Replanned proposal did not contain exactly one replacement step.",
                    step_id=step.id,
                    tool_name=step.tool_name,
                )
                self._emit(
                    state,
                    EventType.RECOVERY_APPLIED,
                    EventOutcome.FAILED,
                    "Recovery stopped because the revised work was ambiguous.",
                    step_id=step.id,
                    tool_name=step.tool_name,
                )
                self._fail_run(
                    state,
                    "Replanned plan must contain one replacement for the failed step.",
                    category=FailureCategory.INVALID_ARGUMENT,
                )
                return None
            replacement = replacement_steps[0]
            state.active_plan = revised
            state.step_statuses.setdefault(replacement.id, StepStatus.PENDING)
            state.retry_counts.setdefault(replacement.id, state.retry_counts.get(step.id, 0))
            self._emit(
                state,
                EventType.RECOVERY_APPLIED,
                EventOutcome.RECOVERED,
                "Validated one-step plan revision; executing its replacement step.",
                step_id=replacement.id,
                tool_name=replacement.tool_name,
            )
            self._transition(state, RunState.EXECUTING)
            self._execute_step(state, replacement)
            if state.step_statuses.get(replacement.id) == StepStatus.SUCCEEDED:
                state.step_statuses[step.id] = StepStatus.SUCCEEDED
                state.step_failures.pop(step.id, None)
            else:
                state.step_statuses[step.id] = StepStatus.FAILED
                state.step_failures[step.id] = failure
                self._emit(
                    state,
                    EventType.STEP_FAILED,
                    EventOutcome.FAILED,
                    "Original step remained failed after its replacement failed.",
                    step_id=step.id,
                    tool_name=step.tool_name,
                )
            return None
        self._emit(
            state,
            EventType.RECOVERY_APPLIED,
            EventOutcome.RECOVERED if action.kind in {RecoveryKind.RETRY, RecoveryKind.FALLBACK} else EventOutcome.FAILED,
            f"Recovery decision: {action.kind.value} ({action.reason_code.value}).",
            step_id=step.id,
            tool_name=action.replacement_call.tool_name if action.replacement_call else step.tool_name,
            attempt=attempt + 1 if action.replacement_call else attempt,
        )
        if action.kind in {RecoveryKind.MARK_FAILED, RecoveryKind.REPLAN}:
            if action.reason_code == RecoveryReason.BUDGET_EXHAUSTED:
                exhausted = failure.model_copy(
                    update={
                        "category": FailureCategory.RETRY_EXHAUSTED,
                        "origin": FailureOrigin.EXECUTOR,
                        "retryability": Retryability.NON_RETRYABLE,
                        "message": (
                            f"Retry budget exhausted after {attempt} tool attempts; "
                            f"last failure: {failure.message}"
                        ),
                    }
                )
                failure = exhausted
                state.failures.append(exhausted)
            self._record_permanent_failure(
                state,
                step.id,
                failure,
            )
            return None
        self._transition(state, RunState.EXECUTING)
        return action

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
        failure: Failure,
    ) -> None:
        state.step_statuses[step_id] = StepStatus.FAILED
        state.step_failures[step_id] = failure
        if failure not in state.failures:
            state.failures.append(failure)
        if state.lifecycle_state == RunState.EXECUTING:
            self._transition(state, RunState.RECOVERY)
        if state.lifecycle_state == RunState.RECOVERY:
            self._transition(state, RunState.EXECUTING)
        self._emit(
            state,
            EventType.STEP_FAILED,
            EventOutcome.FAILED,
            f"Step failed ({failure.category.value}).",
            step_id=step_id,
            tool_name=(
                next(
                    (step.tool_name for step in state.active_plan.steps if step.id == step_id),
                    None,
                )
                if state.active_plan is not None
                else None
            ),
        )

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
            if not isinstance(step.input, SearchResultReference):
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
    def _resolve_search_reference(
        reference: SearchResultReference, state: AgentState,
    ) -> URLFetchInput:
        if state.step_statuses.get(reference.search_step_id) != StepStatus.SUCCEEDED:
            raise ValueError("search dependency has not succeeded")
        call_ids = {call.call_id for call in state.tool_calls
                    if call.step_id == reference.search_step_id
                    and call.tool_name == ToolName.WEB_SEARCH}
        for result in reversed(state.tool_results):
            if (result.call_id in call_ids
                    and result.status == ToolResultStatus.SUCCEEDED
                    and isinstance(result.output, SearchResults)):
                if reference.result_index >= len(result.output.results):
                    raise ValueError("search result index is unavailable")
                return URLFetchInput(url=result.output.results[reference.result_index].url)
        raise ValueError("search result is unavailable")

    @staticmethod
    def _url_is_authorized(arguments: BaseModel, state: AgentState) -> bool:
        url = getattr(arguments, "url", None)
        if not isinstance(url, str):
            return False
        if url in state.goal.text:
            return True
        normalized_url = url.rstrip("/")
        return any(
            result.status == ToolResultStatus.SUCCEEDED
            and isinstance(result.output, SearchResults)
            and any(candidate.url.rstrip("/") == normalized_url for candidate in result.output.results)
            for result in state.tool_results
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

    def _fail_run(
        self,
        state: AgentState,
        message: str,
        *,
        category: FailureCategory = FailureCategory.STATE_INVARIANT,
    ) -> None:
        failure = Failure(
            category=category,
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
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = state.record_event(
            event_type,
            outcome=outcome,
            summary=summary,
            step_id=step_id,
            call_id=call_id,
            tool_name=tool_name,
            attempt=attempt,
            metadata=metadata,
        )
        self._event_logger.emit(event)

    def _transition(
        self, state: AgentState, target: RunState, *, summary: str | None = None
    ) -> None:
        event = state.transition(target, summary=summary)
        self._event_logger.emit(event)
