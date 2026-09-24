from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from research_agent.limits import MAX_MODEL_ATTEMPTS, MAX_PLAN_STEPS
from research_agent.models import Goal, LLMResponse, Plan
from research_agent.planner import Planner, PlannerOutputError, PlannerProviderError
from research_agent.providers.groq import GroqLLMError
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
                "input": {"search_step_id": "search-recent", "result_index": 0},
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


@pytest.mark.parametrize("retry_after, expected_delay", [(3.5, 3.5), (None, 60.0), (0.0, 0.0)])
def test_rate_limit_waits_before_single_retry(retry_after, expected_delay) -> None:
    goal = make_goal()
    timeline = []
    reasons = []
    class LimitedClient:
        def generate(self, *args):
            timeline.append("call")
            if timeline.count("call") == 1:
                raise GroqLLMError("http_429_rate_limit_exceeded", retryable=True,
                    retry_after_seconds=retry_after)
            return LLMResponse(content=json.dumps(valid_plan_payload(goal)), provider="fake")
    plan = Planner(LimitedClient(), make_registry(), sleep=lambda delay: timeline.append(delay)).propose(
        goal, on_retry=reasons.append)
    assert plan.goal_id == goal.goal_id
    assert timeline == ["call", expected_delay, "call"]
    assert "waiting" in reasons[0] and "http_429" in reasons[0]


@pytest.mark.parametrize("category, retryable, delay, attempts, waits", [
    ("http_429_rate_limit_exceeded", True, 2.0, 2, [2.0]),
    ("http_429_rate_limit_exceeded", True, 86400.0, 1, []),
    ("http_401", False, None, 1, []),
    ("http_503", True, None, 2, [1.0]),
])
def test_provider_failure_honors_attempt_and_wait_budgets(category, retryable, delay, attempts, waits) -> None:
    calls = []
    sleeps = []
    class FailingClient:
        def generate(self, *args):
            calls.append(args)
            raise GroqLLMError(category, retryable=retryable, retry_after_seconds=delay)
    with pytest.raises(PlannerProviderError) as caught:
        Planner(FailingClient(), make_registry(), sleep=sleeps.append).propose(make_goal())
    assert len(calls) == caught.value.attempts == attempts
    assert sleeps == waits
    assert caught.value.retry_after_seconds == delay


def test_malformed_plan_then_rate_limit_does_not_start_a_third_attempt() -> None:
    timeline = []
    class RepairLimitedClient:
        def generate(self, *args):
            timeline.append("call")
            if timeline.count("call") == 1:
                return LLMResponse(content="{}", provider="fake")
            raise GroqLLMError("http_429_rate_limit_exceeded", retryable=True, retry_after_seconds=10)
    with pytest.raises(PlannerProviderError) as caught:
        Planner(RepairLimitedClient(), make_registry(), sleep=timeline.append).propose(make_goal())
    assert timeline == ["call", 60.0, "call"]
    assert caught.value.attempts == 2
    assert caught.value.category == "http_429_rate_limit_exceeded"


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


def test_planner_repairs_guessed_fetch_url_before_execution() -> None:
    goal = make_goal()
    broken = valid_plan_payload(goal)
    broken["steps"][1]["input"] = {"url": "https://example.org/guessed"}
    client = FakeLLMClient([json.dumps(broken), json.dumps(valid_plan_payload(goal))])
    waits: list[float] = []
    plan = Planner(client, make_registry(), sleep=waits.append).propose(goal)
    assert plan.steps[1].input.search_step_id == "search-recent"
    assert client.calls[1][1]["validation_errors"] == "fetch_requires_search_result_reference"
    assert waits == [60]


def test_planner_accepts_fetch_url_supplied_in_goal() -> None:
    goal = Goal(text="Read https://example.org/report", run_started_at=datetime.now(timezone.utc))
    payload = valid_plan_payload(goal)
    payload["steps"][1]["input"] = {"url": "https://example.org/report"}
    client = FakeLLMClient([json.dumps(payload)])
    plan = Planner(client, make_registry()).propose(goal)
    assert plan.steps[1].input.url == "https://example.org/report"


def test_planner_repairs_malformed_output_once() -> None:
    goal = make_goal()
    valid = json.dumps(valid_plan_payload(goal))
    client = FakeLLMClient(["{not json", valid])

    waits = []
    plan = Planner(client, make_registry(), sleep=waits.append).propose(goal)

    assert plan.goal_id == goal.goal_id
    assert len(client.calls) == MAX_MODEL_ATTEMPTS
    assert waits == [60.0]
    assert client.calls[1][1]["invalid_response"] == "{not json"
    assert "untrusted data" in client.calls[1][1]["instruction"]
    assert "tool_registry" in client.calls[1][1]


def test_planner_retry_is_reported_without_exposing_malformed_payload() -> None:
    goal = make_goal()
    client = FakeLLMClient(["api_key=secret-value; not json", json.dumps(valid_plan_payload(goal))])
    retry_events: list[str] = []

    Planner(client, make_registry(), sleep=lambda _: None).propose(goal, on_retry=retry_events.append)

    assert retry_events == ["malformed structured planner output (plan: json_invalid); waiting 60s before model attempt 2/2"]
    assert "secret-value" not in retry_events[0]


def test_repair_receives_safe_field_errors() -> None:
    goal = make_goal()
    broken = valid_plan_payload(goal)
    del broken["steps"][0]["objective"]
    broken["secret-value"] = "sensitive-content"
    client = FakeLLMClient([json.dumps(broken), json.dumps(valid_plan_payload(goal))])
    reasons: list[str] = []
    Planner(client, make_registry(), sleep=lambda _: None).propose(goal, on_retry=reasons.append)
    feedback = client.calls[1][1]["validation_errors"]
    assert "steps.0.objective: missing" in feedback
    assert "<field>: extra_forbidden" in feedback
    assert "secret-value" not in feedback
    assert "sensitive-content" not in feedback
    assert feedback in reasons[0]


def test_exhausted_goal_mismatch_preserves_safe_diagnostic() -> None:
    goal = make_goal()
    broken = valid_plan_payload(goal)
    broken["goal_id"] = str(uuid4())
    client = FakeLLMClient([json.dumps(broken)] * MAX_MODEL_ATTEMPTS)
    with pytest.raises(PlannerOutputError) as caught:
        Planner(client, make_registry(), sleep=lambda _: None).propose(goal)
    assert caught.value.reason == "goal_id_mismatch"
    assert caught.value.attempts == MAX_MODEL_ATTEMPTS


def test_invalid_fetch_feedback_excludes_unrelated_union_branches() -> None:
    goal = make_goal()
    broken = valid_plan_payload(goal)
    broken["steps"][1]["input"] = {"url": "<search result>"}
    client = FakeLLMClient([json.dumps(broken)] * MAX_MODEL_ATTEMPTS)
    with pytest.raises(PlannerOutputError) as caught:
        Planner(client, make_registry(), sleep=lambda _: None).propose(goal)
    assert caught.value.reason == "steps.1.input.url: value_error"


def test_planner_accepts_search_reference() -> None:
    goal = make_goal()
    payload = valid_plan_payload(goal)
    payload["steps"][1]["input"] = {"search_step_id": "search-recent", "result_index": 0}
    client = FakeLLMClient([json.dumps(payload)])
    plan = Planner(client, make_registry()).propose(goal)
    assert plan.steps[1].input.search_step_id == "search-recent"


@pytest.mark.parametrize("change", ["missing_dependency", "wrong_tool", "negative_index", "extra_field"])
def test_invalid_search_references_rejected(change: str) -> None:
    goal = make_goal()
    payload = valid_plan_payload(goal)
    step = payload["steps"][1]
    step["input"] = {"search_step_id": "search-recent", "result_index": 0}
    if change == "missing_dependency":
        step["dependencies"] = []
    elif change == "wrong_tool":
        step["tool_name"] = "calculator"
    elif change == "negative_index":
        step["input"]["result_index"] = -1
    else:
        step["input"]["expression"] = "arbitrary path"
    client = FakeLLMClient([json.dumps(payload)] * MAX_MODEL_ATTEMPTS)
    with pytest.raises(PlannerOutputError):
        Planner(client, make_registry(), sleep=lambda _: None).propose(goal)


def test_planner_rejects_tools_missing_from_runtime_registry() -> None:
    goal = make_goal()
    invalid_plan = json.dumps(valid_plan_payload(goal))
    client = FakeLLMClient([invalid_plan, invalid_plan])
    calculator_only = ToolRegistry([CalculatorTool()])

    with pytest.raises(PlannerOutputError):
        Planner(client, calculator_only, sleep=lambda _: None).propose(goal)

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
        Planner(client, make_registry(), sleep=lambda _: None).propose(goal)

    assert failure.value.attempts == MAX_MODEL_ATTEMPTS
    assert len(client.calls) == MAX_MODEL_ATTEMPTS


def test_execution_and_retry_limits_are_declared() -> None:
    from research_agent.limits import MAX_EXECUTION_STEPS, MAX_MODEL_RETRIES, MAX_RETRIES_PER_STEP

    assert MAX_PLAN_STEPS == 8
    assert MAX_EXECUTION_STEPS == 20
    assert MAX_MODEL_RETRIES == 1
    assert MAX_RETRIES_PER_STEP == 2


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
