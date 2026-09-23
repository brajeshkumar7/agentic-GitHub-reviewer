from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from research_agent.event_logger import EventLogger
from research_agent.config import AgentSettings
from research_agent.execution_engine import ExecutionEngine
from research_agent.limits import MAX_EXECUTION_STEPS, MAX_TOOL_ATTEMPTS
from research_agent.models import (
    Calculation,
    CalculatorInput,
    EventType,
    FailureCategory,
    Failure,
    Goal,
    Plan,
    PlanStep,
    Retryability,
    RunState,
    StepStatus,
    ToolCall,
    ToolCallKind,
    ToolName,
    ToolResult,
    ToolResultStatus,
    ValidatedPlan,
)
from research_agent.plan_validator import PlanValidator
from research_agent.state import AgentState
from research_agent.tools.calculator import CalculatorTool
from research_agent.tools.registry import ToolRegistry
from research_agent.tools.base import failed_tool_result


class FakeCalculatorTool(CalculatorTool):
    def __init__(self, outcomes: list[str] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[str] = []

    def execute(self, call: ToolCall) -> ToolResult:
        expression = call.arguments.expression or "1+1"
        self.calls.append(call.step_id)
        outcome = self.outcomes.pop(0) if self.outcomes else "success"
        now = datetime.now(timezone.utc)
        if outcome == "timeout":
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.TIMEOUT,
                retryability=Retryability.RETRYABLE,
                message="Fake timeout.",
                started_at=now,
            )
        if outcome == "failure":
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.CALCULATOR_ERROR,
                retryability=Retryability.NON_RETRYABLE,
                message="Fake deterministic calculation failure.",
                started_at=now,
            )
        if outcome == "malformed":
            return {"unexpected": "payload"}  # type: ignore[return-value]
        return ToolResult(
            call_id=call.call_id,
            status=ToolResultStatus.SUCCEEDED,
            output=Calculation(expression=expression, result=Decimal("2")),
            started_at=now,
            finished_at=now,
        )


class MalformedResultRegistry:
    def __init__(self, tool: FakeCalculatorTool) -> None:
        self._registry = ToolRegistry([tool])

    def get(self, name: str) -> Any:
        return self._registry.get(name)

    def metadata(self) -> Any:
        return self._registry.metadata()

    def validate_arguments(self, name: str, arguments: Any) -> Any:
        return self._registry.validate_arguments(name, arguments)

    def dispatch(self, call: ToolCall) -> Any:
        return object()


def make_plan(goal: Goal, steps: list[PlanStep] | None = None) -> Plan:
    return Plan(
        goal_id=goal.goal_id,
        steps=steps
        or [
            PlanStep(
                id="calculate",
                objective="Calculate the requested value",
                tool_name=ToolName.CALCULATOR,
                input=CalculatorInput(expression="1+1"),
                expected_output="A validated numeric result",
                dependencies=[],
                status=StepStatus.PENDING,
            )
        ],
    )


def ready_state(goal: Goal) -> AgentState:
    state = AgentState.for_goal(goal, uuid4())
    state.transition(RunState.PLANNING)
    state.transition(RunState.PLAN_VALIDATION)
    return state


def execute_with_registry(
    *,
    tool: FakeCalculatorTool,
    plan: Plan,
    state: AgentState,
    registry: Any | None = None,
    logger: EventLogger | None = None,
    bypass_validator: bool = False,
) -> AgentState:
    actual_registry = registry or ToolRegistry([tool])
    validated_plan: ValidatedPlan
    if bypass_validator:
        validated_plan = ValidatedPlan(plan=plan, validator_version="test")
    else:
        validated = PlanValidator().validate(
            state.goal, plan, state, actual_registry
        )
        if isinstance(validated, Failure):
            raise AssertionError(f"test plan did not validate: {validated.message}")
        validated_plan = validated
    return ExecutionEngine(actual_registry, event_logger=logger).execute(
        validated_plan, state
    )


def test_executes_steps_sequentially_in_dependency_order_and_records_events() -> None:
    goal = Goal(text="Calculate two values", run_started_at=datetime.now(timezone.utc))
    steps = [
        PlanStep(
            id="second",
            objective="Calculate the second value after the first",
            tool_name=ToolName.CALCULATOR,
            input=CalculatorInput(expression="2+2"),
            expected_output="Second numeric result",
            dependencies=["first"],
            status=StepStatus.PENDING,
        ),
        PlanStep(
            id="first",
            objective="Calculate the first value",
            tool_name=ToolName.CALCULATOR,
            input=CalculatorInput(expression="1+1"),
            expected_output="First numeric result",
            dependencies=[],
            status=StepStatus.PENDING,
        ),
    ]
    plan = make_plan(goal, steps)
    state = ready_state(goal)
    tool = FakeCalculatorTool()
    logger = EventLogger()

    result = execute_with_registry(
        tool=tool, plan=plan, state=state, logger=logger
    )

    assert tool.calls == ["first", "second"]
    assert result.step_statuses == {
        "first": StepStatus.SUCCEEDED,
        "second": StepStatus.SUCCEEDED,
    }
    assert len(result.tool_results) == 2
    assert result.lifecycle_state is RunState.SYNTHESIZING
    assert [event.sequence for event in result.events] == list(
        range(1, len(result.events) + 1)
    )
    assert result.events[-1].event_type is EventType.STATE_TRANSITION
    assert len(logger.events) > 0
    assert any(event.event_type is EventType.TOOL_CALL_SUCCEEDED for event in logger.events)


def test_failed_step_skips_dependents_and_continues_independent_work() -> None:
    goal = Goal(text="Calculate values", run_started_at=datetime.now(timezone.utc))
    plan = make_plan(
        goal,
        [
            PlanStep(
                id="fails",
                objective="Attempt the first calculation",
                tool_name=ToolName.CALCULATOR,
                input=CalculatorInput(expression="1+1"),
                expected_output="First result",
                dependencies=[],
                status=StepStatus.PENDING,
            ),
            PlanStep(
                id="dependent",
                objective="Use the first result",
                tool_name=ToolName.CALCULATOR,
                input=CalculatorInput(expression="2+2"),
                expected_output="Dependent result",
                dependencies=["fails"],
                status=StepStatus.PENDING,
            ),
            PlanStep(
                id="independent",
                objective="Perform an independent calculation",
                tool_name=ToolName.CALCULATOR,
                input=CalculatorInput(expression="3+3"),
                expected_output="Independent result",
                dependencies=[],
                status=StepStatus.PENDING,
            ),
        ],
    )
    tool = FakeCalculatorTool(["failure", "success"])
    state = execute_with_registry(tool=tool, plan=plan, state=ready_state(goal))

    assert tool.calls == ["fails", "independent"]
    assert state.step_statuses["fails"] is StepStatus.FAILED
    assert state.step_statuses["dependent"] is StepStatus.SKIPPED
    assert state.step_statuses["independent"] is StepStatus.SUCCEEDED
    assert "fails" in state.step_failures
    assert any(event.event_type is EventType.STEP_SKIPPED for event in state.events)


def test_unknown_unregistered_tool_fails_run_without_dispatch() -> None:
    goal = Goal(text="Search for sources", run_started_at=datetime.now(timezone.utc))
    plan = Plan(
        goal_id=goal.goal_id,
        steps=[
            PlanStep(
                id="search",
                objective="Find candidate sources",
                tool_name=ToolName.WEB_SEARCH,
                input={"query": "RAG", "max_results": 2},
                expected_output="Candidate sources",
                dependencies=[],
                status=StepStatus.PENDING,
            )
        ],
    )
    state = ready_state(goal)
    tool = FakeCalculatorTool()

    result = execute_with_registry(
        tool=tool, plan=plan, state=state, bypass_validator=True
    )

    assert result.lifecycle_state is RunState.FAILED
    assert result.tool_calls == []
    assert result.failures
    assert result.events[-1].event_type is EventType.STATE_TRANSITION


def test_malformed_registry_result_is_recorded_as_failure() -> None:
    goal = Goal(text="Calculate value", run_started_at=datetime.now(timezone.utc))
    state = execute_with_registry(
        tool=FakeCalculatorTool(),
        plan=make_plan(goal),
        state=ready_state(goal),
        registry=MalformedResultRegistry(FakeCalculatorTool()),
    )

    assert state.step_statuses["calculate"] is StepStatus.FAILED
    assert state.tool_results[0].failure is not None
    assert state.tool_results[0].failure.category is FailureCategory.INVALID_RESPONSE


def test_timeout_retries_twice_and_never_exceeds_configured_attempts() -> None:
    goal = Goal(text="Calculate value", run_started_at=datetime.now(timezone.utc))
    tool = FakeCalculatorTool(["timeout", "timeout", "success"])
    state = execute_with_registry(tool=tool, plan=make_plan(goal), state=ready_state(goal))

    assert tool.calls == ["calculate"] * MAX_TOOL_ATTEMPTS
    assert len(state.tool_calls) == MAX_TOOL_ATTEMPTS
    assert state.retry_counts["calculate"] == 2
    assert state.step_statuses["calculate"] is StepStatus.SUCCEEDED
    assert sum(event.event_type is EventType.RETRY_ATTEMPTED for event in state.events) == 2


def test_run_wide_dispatch_budget_prevents_additional_tool_execution() -> None:
    goal = Goal(text="Calculate value", run_started_at=datetime.now(timezone.utc))
    state = ready_state(goal)
    state.tool_calls = [
        ToolCall(
            run_id=state.run_id,
            step_id=f"prior-{index}",
            tool_name=ToolName.CALCULATOR,
            arguments=CalculatorInput(expression="1+1"),
            attempt=1,
            kind=ToolCallKind.PRIMARY,
            created_at=datetime.now(timezone.utc),
        )
        for index in range(MAX_EXECUTION_STEPS)
    ]
    tool = FakeCalculatorTool()

    result = execute_with_registry(tool=tool, plan=make_plan(goal), state=state)

    assert len(result.tool_calls) == MAX_EXECUTION_STEPS
    assert tool.calls == []
    assert result.step_statuses["calculate"] is StepStatus.SKIPPED


def test_successful_execution_stores_validated_results() -> None:
    goal = Goal(text="Calculate value", run_started_at=datetime.now(timezone.utc))
    state = execute_with_registry(
        tool=FakeCalculatorTool(), plan=make_plan(goal), state=ready_state(goal)
    )

    assert state.tool_results[0].status is ToolResultStatus.SUCCEEDED
    assert isinstance(state.tool_results[0].output, Calculation)


def test_terminal_transition_failure_is_represented_and_terminal() -> None:
    goal = Goal(text="Find sources", run_started_at=datetime.now(timezone.utc))
    state = ready_state(goal)
    state.transition(RunState.FAILED, summary="No trustworthy result can be produced.")

    with pytest.raises(ValueError, match="illegal lifecycle transition"):
        state.transition(RunState.EXECUTING)
