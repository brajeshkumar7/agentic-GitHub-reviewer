from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from research_agent.limits import MAX_MODEL_ATTEMPTS, MAX_PLAN_STEPS
from research_agent.models import Goal, LLMResponse, Plan
from research_agent.planner import Planner, PlannerOutputError
from research_agent.tools.calculator import CalculatorTool
from research_agent.tools.registry import ToolRegistry
from research_agent.tools.url_fetch import URLFetchTool
from research_agent.tools.web_search import WebSearchTool


def make_goal() -> Goal:
    return Goal(text="Research recent RAG systems", run_started_at=datetime.now(timezone.utc))


def valid_plan_payload(goal: Goal) -> dict[str, Any]:
    return {
        "plan_id": str(uuid4()),
        "goal_id": str(goal.goal_id),
        "revision": 1,
        "steps": [
            {
                "id": "search-recent",
                "objective": "Find recent RAG developments",
                "tool_name": "web_search",
                "input": {"query": "recent RAG developments", "max_results": 5},
                "expected_output": "Candidate public sources",
                "dependencies": [],
                "status": "PENDING",
            },
            {
                "id": "fetch-source",
                "objective": "Read a candidate source",
                "tool_name": "url_fetch",
                "input": {"url": "https://example.org/report"},
                "expected_output": "Source text and metadata",
                "dependencies": ["search-recent"],
                "status": "PENDING",
            },
        ],
    }


class FakeLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    def generate(
        self, operation: str, payload: dict[str, Any], expected_schema: str
    ) -> LLMResponse:
        self.calls.append((operation, payload, expected_schema))
        content = self.responses.pop(0)
        return LLMResponse(content=content, provider="fake")


class FakeSearchProvider:
    def search(self, search_input: Any) -> Any:
        raise AssertionError("planner tests must not execute tools")


def make_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            WebSearchTool(provider=FakeSearchProvider()),
            URLFetchTool(),
            CalculatorTool(),
        ]
    )


def test_planner_accepts_valid_structured_output() -> None:
    goal = make_goal()
    client = FakeLLMClient([json.dumps(valid_plan_payload(goal))])

    plan = Planner(client, make_registry()).propose(goal)

    assert len(plan.steps) == 2
    assert plan.steps[0].id == "search-recent"
    assert plan.steps[0].status.value == "PENDING"
    assert client.calls[0][0] == "plan_proposal"
    assert "instruction" in client.calls[0][1]
    tool_registry = client.calls[0][1]["tool_registry"]
    assert [item["name"] for item in tool_registry] == [
        "web_search",
        "url_fetch",
        "calculator",
    ]
    assert all("input_schema" in item for item in tool_registry)
    assert client.calls[0][1]["max_plan_steps"] == MAX_PLAN_STEPS


def test_planner_repairs_malformed_output_once() -> None:
    goal = make_goal()
    valid = json.dumps(valid_plan_payload(goal))
    client = FakeLLMClient(["{not json", valid])

    plan = Planner(client, make_registry()).propose(goal)

    assert plan.goal_id == goal.goal_id
    assert len(client.calls) == MAX_MODEL_ATTEMPTS
    assert client.calls[1][1]["invalid_response"] == "{not json"
    assert "untrusted data" in client.calls[1][1]["instruction"]
    assert "tool_registry" in client.calls[1][1]


def test_planner_rejects_tools_missing_from_runtime_registry() -> None:
    goal = make_goal()
    invalid_plan = json.dumps(valid_plan_payload(goal))
    client = FakeLLMClient([invalid_plan, invalid_plan])
    calculator_only = ToolRegistry([CalculatorTool()])

    with pytest.raises(PlannerOutputError):
        Planner(client, calculator_only).propose(goal)

    assert len(client.calls) == MAX_MODEL_ATTEMPTS
    assert [tool["name"] for tool in client.calls[0][1]["tool_registry"]] == [
        "calculator"
    ]


def remove_required_field(payload: dict[str, Any]) -> None:
    payload["steps"][0].pop("objective")


def add_invalid_tool(payload: dict[str, Any]) -> None:
    payload["steps"][0]["tool_name"] = "shell"


def exceed_step_limit(payload: dict[str, Any]) -> None:
    payload["steps"] = [
        {
            "id": f"step-{index}",
            "objective": "Search for sources",
            "tool_name": "web_search",
            "input": {"query": "RAG", "max_results": 1},
            "expected_output": "Source candidates",
            "dependencies": [],
            "status": "PENDING",
        }
        for index in range(MAX_PLAN_STEPS + 1)
    ]


def add_invalid_dependency(payload: dict[str, Any]) -> None:
    payload["steps"][1]["dependencies"] = ["does-not-exist"]


@pytest.mark.parametrize(
    "mutate",
    [
        remove_required_field,
        add_invalid_tool,
        exceed_step_limit,
        add_invalid_dependency,
    ],
    ids=["missing-field", "unknown-tool", "too-many-steps", "invalid-dependency"],
)
def test_planner_rejects_invalid_plan_after_bounded_retry(mutate: Any) -> None:
    goal = make_goal()
    payload = valid_plan_payload(goal)
    # Each scenario creates an invalid proposal and repeats it after the repair request.
    mutate(payload)
    invalid = json.dumps(payload)
    client = FakeLLMClient([invalid, invalid])

    with pytest.raises(PlannerOutputError) as failure:
        Planner(client, make_registry()).propose(goal)

    assert failure.value.attempts == MAX_MODEL_ATTEMPTS
    assert len(client.calls) == MAX_MODEL_ATTEMPTS


def test_execution_and_retry_limits_are_declared() -> None:
    from research_agent.limits import MAX_EXECUTION_STEPS, MAX_RETRY_COUNT

    assert MAX_PLAN_STEPS == 8
    assert MAX_EXECUTION_STEPS == 20
    assert MAX_RETRY_COUNT == 1


def test_plan_step_json_schema_exposes_required_planner_fields() -> None:
    from research_agent.models import PlanStep

    schema = PlanStep.model_json_schema(by_alias=False)
    required = set(schema["required"])

    assert {
        "id",
        "objective",
        "tool_name",
        "input",
        "expected_output",
        "dependencies",
        "status",
    } <= required
