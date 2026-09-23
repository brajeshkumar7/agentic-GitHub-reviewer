from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from research_agent.models import (
    Failure,
    Goal,
    Plan,
    PlanStep,
    StepStatus,
    ToolName,
    WebSearchInput,
)
from research_agent.plan_validator import PlanValidator
from research_agent.state import AgentState


def test_plan_validator_approves_schema_valid_goal_bound_plan() -> None:
    goal = Goal(text="Find recent RAG research", run_started_at=datetime.now(timezone.utc))
    plan = Plan(
        goal_id=goal.goal_id,
        steps=[
            PlanStep(
                id="search",
                objective="Find candidate sources",
                tool_name=ToolName.WEB_SEARCH,
                input=WebSearchInput(query="recent RAG research", max_results=5),
                expected_output="Candidate source list",
                dependencies=[],
                status=StepStatus.PENDING,
            )
        ],
    )
    state = AgentState.for_goal(goal, uuid4())

    result = PlanValidator().validate(goal, plan, state)

    assert not isinstance(result, Failure)
    assert result.validator_version == "phase3"


def test_plan_validator_rejects_plan_bound_to_different_goal() -> None:
    goal = Goal(text="Goal one", run_started_at=datetime.now(timezone.utc))
    other_goal = Goal(text="Goal two", run_started_at=datetime.now(timezone.utc))
    plan = Plan(
        goal_id=other_goal.goal_id,
        steps=[
            PlanStep(
                id="search",
                objective="Find sources",
                tool_name=ToolName.WEB_SEARCH,
                input=WebSearchInput(query="topic", max_results=1),
                expected_output="Sources",
                dependencies=[],
                status=StepStatus.PENDING,
            )
        ],
    )
    state = AgentState.for_goal(goal, uuid4())

    result = PlanValidator().validate(goal, plan, state)

    assert isinstance(result, Failure)
    assert result.run_id == state.run_id


def test_plan_validator_enforces_single_revision_budget() -> None:
    goal = Goal(text="Goal", run_started_at=datetime.now(timezone.utc))
    active_plan = Plan(
        goal_id=goal.goal_id,
        revision=2,
        steps=[
            PlanStep(
                id="search-old",
                objective="Find sources",
                tool_name=ToolName.WEB_SEARCH,
                input=WebSearchInput(query="topic", max_results=1),
                expected_output="Sources",
                dependencies=[],
                status=StepStatus.PENDING,
            )
        ],
    )
    proposal = Plan(
        goal_id=goal.goal_id,
        revision=3,
        replaces_plan_id=active_plan.plan_id,
        steps=[
            PlanStep(
                id="search-new",
                objective="Find sources again",
                tool_name=ToolName.WEB_SEARCH,
                input=WebSearchInput(query="topic", max_results=1),
                expected_output="Sources",
                dependencies=[],
                status=StepStatus.PENDING,
            )
        ],
    )
    state = AgentState.for_goal(goal, uuid4())
    state.active_plan = active_plan

    result = PlanValidator().validate(goal, proposal, state)

    assert isinstance(result, Failure)
    assert result.category.value == "invalid_argument"
