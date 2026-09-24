from __future__ import annotations

import json
from io import StringIO
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from research_agent.event_logger import EventLogger, JsonlEventLogger
from research_agent.cli import render_trace, write_trace
from research_agent.execution_engine import ExecutionEngine
from research_agent.models import (
    CalculatorInput,
    EventOutcome,
    EventType,
    Goal,
    Plan,
    PlanStep,
    RunState,
    StepStatus,
    ToolName,
    ValidatedPlan,
)
from research_agent.plan_validator import PlanValidator
from research_agent.state import AgentState
from research_agent.tools.calculator import CalculatorTool
from research_agent.tools.registry import ToolRegistry
from research_agent.trace_renderer import TraceRenderer


def test_execution_emits_lifecycle_events_with_required_identifiers() -> None:
    goal = Goal(text="Calculate 1 + 2", run_started_at=datetime.now(timezone.utc))
    plan = Plan(
        goal_id=goal.goal_id,
        steps=[
            PlanStep(
                id="calculate",
                objective="Calculate the requested sum",
                tool_name=ToolName.CALCULATOR,
                input=CalculatorInput(expression="1 + 2"),
                expected_output="A numeric sum",
                dependencies=[],
                status=StepStatus.PENDING,
            )
        ],
    )
    state = AgentState.for_goal(goal, uuid4())
    state.transition(RunState.PLANNING)
    state.transition(RunState.PLAN_VALIDATION)
    registry = ToolRegistry([CalculatorTool()])
    validated = PlanValidator().validate(goal, plan, state, registry)
    assert isinstance(validated, ValidatedPlan)
    logger = EventLogger()

    result = ExecutionEngine(registry, event_logger=logger).execute(validated, state)

    event_types = [event.event_type for event in result.events]
    assert EventType.STEP_STARTED in event_types
    assert EventType.TOOL_CALL_STARTED in event_types
    assert EventType.TOOL_CALL_SUCCEEDED in event_types
    assert EventType.STEP_COMPLETED in event_types
    assert all(event.execution_id == state.run_id for event in logger.events)
    assert all(event.timestamp.tzinfo is not None for event in logger.events)
    assert all(event.status is not None and isinstance(event.metadata, dict) for event in logger.events)


def test_jsonl_logger_appends_redacted_structured_events() -> None:
    goal = Goal(text="Research topic", run_started_at=datetime.now(timezone.utc))
    state = AgentState.for_goal(goal, uuid4())
    event = state.record_event(
        EventType.GOAL_RECEIVED,
        outcome=EventOutcome.SUCCEEDED,
        summary="Goal accepted; token=top-secret-value",
        metadata={"api_key": "top-secret-value", "detail": "Bearer abc123"},
    )
    assert "top-secret-value" not in state.events[-1].summary
    path = Path.cwd() / f".observability-{uuid4()}.jsonl"
    try:
        logger = JsonlEventLogger(path)
        logger.emit(event)
        logger.emit(event)

        serialized = path.read_text(encoding="utf-8")
        rows = [json.loads(line) for line in serialized.splitlines()]
        assert len(rows) == 2
        assert rows[0]["event_id"] == str(event.event_id)
        assert rows[0]["execution_id"] == str(state.run_id)
        assert rows[0]["event_type"] == "GOAL_RECEIVED"
        assert rows[0]["status"] == "succeeded"
        assert rows[0]["metadata"]["api_key"] == "[REDACTED]"
        assert rows[0]["metadata"]["detail"] == "Bearer [REDACTED]"
        assert "top-secret-value" not in serialized
    finally:
        path.unlink(missing_ok=True)


def test_trace_renderer_shows_plan_actions_and_recovery_without_reasoning() -> None:
    goal = Goal(text="Research topic", run_started_at=datetime.now(timezone.utc))
    plan = Plan(
        goal_id=goal.goal_id,
        steps=[
            PlanStep(
                id="search_recent",
                objective="Search recent research token=plan-secret",
                tool_name=ToolName.CALCULATOR,
                input=CalculatorInput(expression="2 + 2"),
                expected_output="A result",
                dependencies=[],
                status=StepStatus.PENDING,
            )
        ],
    )
    state = AgentState.for_goal(goal, uuid4())
    started = state.record_event(
        EventType.TOOL_CALL_STARTED,
        outcome=EventOutcome.STARTED,
        summary="Calculator call started",
        step_id="search_recent",
        tool_name=ToolName.CALCULATOR,
    )
    recovered = state.record_event(
        EventType.RETRY_ATTEMPTED,
        outcome=EventOutcome.SCHEDULED,
        summary="Retrying after a temporary failure",
        step_id="search_recent",
    )
    complete = state.record_event(
        EventType.STEP_COMPLETED,
        outcome=EventOutcome.COMPLETED,
        summary="Step completed",
        step_id="search_recent",
    )

    rendered = TraceRenderer().render(plan, [started, recovered, complete])

    assert "[PLAN]" in rendered and "[EXECUTION]" in rendered
    assert "1. Search recent research" in rendered
    assert "plan-secret" not in rendered
    assert "→ search_recent" in rendered
    assert "↻ search_recent" in rendered
    assert "✓ search_recent" in rendered
    assert "chain-of-thought" not in rendered
    assert render_trace(plan, [started, recovered, complete]) == rendered
    stream = StringIO()
    write_trace(plan, [started, recovered, complete], stream)
    assert stream.getvalue().strip() == rendered
