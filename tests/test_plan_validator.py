from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from research_agent.models import (
    Failure,
    Goal,
    Plan,
    PlanStep,
    StepStatus,
    ToolName,
    URLFetchInput,
    WebSearchInput,
)
from research_agent.plan_validator import PlanValidator
from research_agent.state import AgentState
from research_agent.tools.calculator import CalculatorTool
from research_agent.tools.registry import ToolRegistry
from research_agent.tools.url_fetch import URLFetchTool
from research_agent.tools.web_search import WebSearchTool


class FakeSearchProvider:
    def search(self, search_input: WebSearchInput) -> object:
        raise AssertionError("validator tests must not execute tools")


def make_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            WebSearchTool(provider=FakeSearchProvider()),
            URLFetchTool(),
            CalculatorTool(),
        ]
    )


@pytest.fixture
def goal() -> Goal:
    return Goal(text="Find recent RAG research", run_started_at=datetime.now(timezone.utc))


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

    result = PlanValidator().validate(goal, plan, state, make_registry())

    assert not isinstance(result, Failure)
    assert result.validator_version == "phase3-registry"


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

    result = PlanValidator().validate(goal, plan, state, make_registry())

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

    result = PlanValidator().validate(goal, proposal, state, make_registry())

    assert isinstance(result, Failure)
    assert result.category.value == "invalid_argument"


def _step(step_id: str = "search", **overrides: object) -> dict[str, object]:
    step: dict[str, object] = {
        "id": step_id,
        "objective": "Find three dated sources",
        "tool_name": "web_search",
        "input": {"query": "recent RAG research", "max_results": 3},
        "expected_output": "A list containing up to three dated candidate URLs",
        "dependencies": [],
        "status": "PENDING",
    }
    step.update(overrides)
    return step


def _plan_payload(goal: Goal, steps: list[dict[str, object]]) -> dict[str, object]:
    return {
        "goal_id": str(goal.goal_id),
        "revision": 1,
        "steps": steps,
    }


@pytest.mark.parametrize(
    "steps",
    [
        [_step(objective="")],
        [_step("same"), _step("same")],
        [_step("one", dependencies=["missing"])],
        [_step("one", dependencies=["two"]), _step("two", dependencies=["one"])],
        [_step(tool_name="shell")],
        [_step(input={"query": "RAG", "max_results": 11})],
    ],
    ids=[
        "malformed-step",
        "duplicate-step-ids",
        "missing-dependency",
        "circular-dependencies",
        "unknown-tool",
        "invalid-tool-arguments",
    ],
)
def test_plan_schema_rejects_invalid_proposals(
    goal: Goal, steps: list[dict[str, object]]
) -> None:
    with pytest.raises(ValueError):
        Plan.model_validate(_plan_payload(goal, steps))


def test_plan_validator_rejects_arguments_that_do_not_match_registered_tool() -> None:
    goal = Goal(text="Find sources", run_started_at=datetime.now(timezone.utc))
    forged_step = PlanStep.model_construct(
        id="search",
        objective="Find sources",
        tool_name=ToolName.WEB_SEARCH,
        input=URLFetchInput(url="https://example.org"),
        expected_output="Candidate URLs",
        dependencies=[],
        status=StepStatus.PENDING,
        fallback=None,
        recovery_of_step_id=None,
    )
    forged_plan = Plan.model_construct(
        plan_id=uuid4(),
        goal_id=goal.goal_id,
        revision=1,
        steps=[forged_step],
        replaces_plan_id=None,
    )
    state = AgentState.for_goal(goal, uuid4())

    result = PlanValidator().validate(goal, forged_plan, state, make_registry())

    assert isinstance(result, Failure)
    assert result.origin.value == "validator"
