from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from research_agent.config import AgentSettings
from research_agent.execution_engine import ExecutionEngine
from research_agent.failure_handler import FailureHandler
from research_agent.limits import MAX_RETRIES_PER_STEP
from research_agent.models import (
    Calculation,
    CalculatorInput,
    EventType,
    Failure,
    FailureCategory,
    FailureInjectionMode,
    FailureOrigin,
    FinalReport,
    Goal,
    Plan,
    PlanStep,
    RecoveryKind,
    Retryability,
    RunState,
    StepStatus,
    ToolCall,
    ToolCallKind,
    ToolName,
    ToolResult,
    ToolResultStatus,
    ValidatedPlan,
    ResearchBrief,
    utc_now,
)
from research_agent.state import AgentState
from research_agent.tools.base import failed_tool_result
from research_agent.tools.calculator import CalculatorTool
from research_agent.tools.registry import ToolRegistry


class DemoCalculator(CalculatorTool):
    def __init__(self, fail_repeatedly: bool = False) -> None:
        self.calls = 0
        self.fail_repeatedly = fail_repeatedly

    def execute(self, call: ToolCall) -> ToolResult:
        self.calls += 1
        now = utc_now()
        if self.fail_repeatedly:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.TIMEOUT,
                retryability=Retryability.RETRYABLE,
                message="Synthetic timeout for retry exhaustion test.",
                started_at=now,
            )
        return ToolResult(
            call_id=call.call_id,
            status=ToolResultStatus.SUCCEEDED,
            output=Calculation(expression="1+1", result=Decimal("2")),
            started_at=now,
            finished_at=now,
        )


class EmptyThenSuccessCalculator(DemoCalculator):
    def execute(self, call: ToolCall) -> ToolResult:
        self.calls += 1
        now = utc_now()
        if self.calls == 1:
            return failed_tool_result(
                call_id=call.call_id,
                run_id=call.run_id,
                step_id=call.step_id,
                category=FailureCategory.EMPTY_RESULTS,
                retryability=Retryability.SEMANTIC,
                message="No usable result was returned.",
                started_at=now,
            )
        return ToolResult(
            call_id=call.call_id,
            status=ToolResultStatus.SUCCEEDED,
            output=Calculation(expression="2+2", result=Decimal("4")),
            started_at=now,
            finished_at=now,
        )


def ready_run() -> tuple[Goal, AgentState, Plan]:
    goal = Goal(text="Calculate 1 + 1", run_started_at=utc_now())
    step = PlanStep(
        id="calc",
        objective="Calculate the sum of 1 and 1",
        tool_name=ToolName.CALCULATOR,
        input=CalculatorInput(expression="1+1"),
        expected_output="A numeric result equal to 2",
        dependencies=[],
        status=StepStatus.PENDING,
    )
    plan = Plan(goal_id=goal.goal_id, steps=[step])
    state = AgentState.for_goal(goal, uuid4())
    state.transition(RunState.PLANNING)
    state.transition(RunState.PLAN_VALIDATION)
    return goal, state, plan


def final_report(state: AgentState, plan: Plan) -> FinalReport:
    """Test-only deterministic synthesis boundary for the end-to-end scenario."""
    now = utc_now()
    return FinalReport(
        run_id=state.run_id,
        status=RunState.COMPLETED if not state.step_failures else RunState.PARTIAL,
        goal=state.goal.text,
        run_started_at=state.goal.run_started_at,
        run_finished_at=now,
        research_brief=ResearchBrief(
            topic="test arithmetic",
            time_window_start=state.goal.run_started_at,
            time_window_end=now,
            summary="The planned calculation completed after bounded recovery.",
            developments=[],
            comparison="Not applicable.",
            conclusion="The computed result is 2.",
        ),
        plan=plan,
        failures=state.failures,
        limitations=([] if not state.step_failures else [
            f"Step calc failed: {state.step_failures['calc'].message}"
        ]),
    )


def test_injected_timeout_recovers_and_produces_successful_structured_report(monkeypatch) -> None:
    _, state, plan = ready_run()
    tool = DemoCalculator()
    monkeypatch.setenv("AGENT_INJECT_FAILURE", "true")
    monkeypatch.setenv("AGENT_FAILURE_MODE", "tool_timeout")
    monkeypatch.setenv("AGENT_FAILURE_TOOL", "calculator")
    registry = ToolRegistry([tool])
    state = ExecutionEngine(registry).execute(
        ValidatedPlan(plan=plan), state
    )
    report = final_report(state, state.active_plan or plan)

    event_types = [event.event_type for event in state.events]
    assert state.lifecycle_state is RunState.SYNTHESIZING
    assert state.step_statuses["calc"] is StepStatus.SUCCEEDED
    assert tool.calls == 1  # injected call bypasses the fake tool; bounded retry succeeds
    assert EventType.FAILURE_INJECTED in event_types
    assert EventType.RECOVERY_STARTED in event_types
    assert EventType.RETRY_ATTEMPTED in event_types
    assert EventType.TOOL_CALL_SUCCEEDED in event_types
    assert report.status is RunState.COMPLETED
    assert len(state.tool_calls) == 2
    assert [call.attempt for call in state.tool_calls] == [1, 2]


def test_injected_malformed_response_uses_the_same_recovery_path() -> None:
    _, state, plan = ready_run()
    tool = DemoCalculator()
    settings = AgentSettings(
        agent_inject_failure=True,
        agent_failure_mode=FailureInjectionMode.MALFORMED_TOOL_RESPONSE,
    )
    state = ExecutionEngine(ToolRegistry([tool]), settings=settings).execute(
        ValidatedPlan(plan=plan), state
    )

    assert state.step_statuses["calc"] is StepStatus.SUCCEEDED
    assert state.tool_results[0].failure.category is FailureCategory.INVALID_RESPONSE
    assert state.recovery_history[0].kind is RecoveryKind.RETRY
    assert tool.calls == 1


def test_retry_exhaustion_preserves_failed_step_and_final_report_limitation() -> None:
    _, state, plan = ready_run()
    tool = DemoCalculator(fail_repeatedly=True)
    state = ExecutionEngine(ToolRegistry([tool])).execute(ValidatedPlan(plan=plan), state)
    report = final_report(state, state.active_plan or plan)

    assert tool.calls == MAX_RETRIES_PER_STEP + 1
    assert state.retry_counts["calc"] == MAX_RETRIES_PER_STEP
    assert state.step_statuses["calc"] is StepStatus.FAILED
    assert "Step calc failed" in report.limitations[0]
    assert "Retry budget exhausted" in report.limitations[0]
    assert report.status is RunState.PARTIAL


def test_replanning_is_selected_only_for_recoverable_semantic_failure() -> None:
    _, state, plan = ready_run()
    step = plan.steps[0]
    call = ToolCall(
        run_id=state.run_id,
        step_id=step.id,
        tool_name=step.tool_name,
        arguments=step.input,
        attempt=1,
        kind=ToolCallKind.PRIMARY,
        created_at=utc_now(),
    )
    state.active_plan = plan
    state.tool_calls.append(call)
    failure = Failure(
        category=FailureCategory.EMPTY_RESULTS,
        origin=FailureOrigin.TOOL,
        retryability=Retryability.SEMANTIC,
        run_id=state.run_id,
        step_id=step.id,
        call_id=call.call_id,
        message="No candidates were returned.",
        occurred_at=utc_now(),
    )
    action = FailureHandler(replanning_enabled=True).recover(failure, state, step)
    assert action.kind is RecoveryKind.REPLAN


def test_semantic_failure_uses_only_a_validated_declared_fallback() -> None:
    _, state, plan = ready_run()
    step = PlanStep.model_validate(
        {
            **plan.steps[0].model_dump(),
            "fallback": {
                "tool_name": ToolName.CALCULATOR,
                "arguments": CalculatorInput(expression="3+3"),
            },
        }
    )
    call = ToolCall(
        run_id=state.run_id,
        step_id=step.id,
        tool_name=step.tool_name,
        arguments=step.input,
        attempt=1,
        kind=ToolCallKind.PRIMARY,
        created_at=utc_now(),
    )
    state.tool_calls.append(call)
    failure = Failure(
        category=FailureCategory.EMPTY_RESULTS,
        origin=FailureOrigin.TOOL,
        retryability=Retryability.SEMANTIC,
        run_id=state.run_id,
        step_id=step.id,
        call_id=call.call_id,
        message="Search returned no results.",
        occurred_at=utc_now(),
    )

    action = FailureHandler().recover(failure, state, step)

    assert action.kind is RecoveryKind.FALLBACK
    assert action.replacement_call.kind is ToolCallKind.FALLBACK
    assert action.replacement_call.arguments.expression == "3+3"


def test_failure_injection_environment_configuration_is_validated() -> None:
    from research_agent.models import FailureInjectionMode

    settings = AgentSettings.from_env(
        {
            "AGENT_INJECT_FAILURE": "true",
            "AGENT_FAILURE_MODE": "malformed_tool_response",
            "AGENT_FAILURE_TOOL": "calculator",
        }
    )
    assert settings.agent_inject_failure
    assert settings.agent_failure_mode is FailureInjectionMode.MALFORMED_TOOL_RESPONSE
    assert settings.agent_failure_tool is ToolName.CALCULATOR


def test_validated_replan_executes_one_replacement_and_recovers_logical_step() -> None:
    _, state, original = ready_run()
    tool = EmptyThenSuccessCalculator()
    registry = ToolRegistry([tool])

    def replan(goal: Goal, current: AgentState, failure: Failure) -> Plan:
        del goal, current, failure
        return Plan(
            goal_id=original.goal_id,
            revision=2,
            replaces_plan_id=original.plan_id,
            steps=[
                PlanStep(
                    id="calc-revised",
                    objective="Retry the calculation using a revised expression",
                    tool_name=ToolName.CALCULATOR,
                    input=CalculatorInput(expression="2+2"),
                    expected_output="A numeric result equal to 4",
                    dependencies=[],
                    status=StepStatus.PENDING,
                    recovery_of_step_id="calc",
                )
            ],
        )

    state = ExecutionEngine(registry, replanner=replan).execute(
        ValidatedPlan(plan=original), state
    )
    assert state.lifecycle_state is RunState.SYNTHESIZING
    assert state.active_plan.revision == 2
    assert state.step_statuses["calc"] is StepStatus.SUCCEEDED
    assert state.step_statuses["calc-revised"] is StepStatus.SUCCEEDED
    assert any(action.kind is RecoveryKind.REPLAN for action in state.recovery_history)
    assert tool.calls == 2
    assert [call.attempt for call in state.tool_calls] == [1, 2]


def test_invalid_replan_is_a_terminal_run_failure() -> None:
    _, state, original = ready_run()
    tool = EmptyThenSuccessCalculator()

    def invalid_replan(goal: Goal, current: AgentState, failure: Failure) -> Plan:
        del goal, current, failure
        return original  # revision 1 cannot replace an already validated plan

    state = ExecutionEngine(ToolRegistry([tool]), replanner=invalid_replan).execute(
        ValidatedPlan(plan=original), state
    )
    assert state.lifecycle_state is RunState.FAILED
    assert any("Invalid plan after" in failure.message for failure in state.failures)

