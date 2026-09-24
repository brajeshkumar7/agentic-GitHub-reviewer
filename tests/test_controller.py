from __future__ import annotations

import json
from datetime import datetime, timezone
from collections.abc import Callable
from uuid import uuid4

from research_agent.controller import AgentController
from research_agent.evidence_store import EvidenceStore
from research_agent.event_logger import EventLogger
from research_agent.execution_engine import ExecutionEngine
from research_agent.models import (
    CalculatorInput,
    EventType,
    FetchedPage,
    Failure,
    Goal,
    LLMResponse,
    Plan,
    PlanStep,
    SearchResult,
    SearchResults,
    SearchResultReference,
    RunState,
    StepStatus,
    ToolName,
    URLFetchInput,
    ValidatedPlan,
    WebSearchInput,
    utc_now,
)
from research_agent.plan_validator import PlanValidator
from research_agent.planner import PlannerOutputError, PlannerProviderError, Planner
from research_agent.providers.groq import GroqLLMError
from research_agent.report_generator import ReportGenerator
from research_agent.state import AgentState
from research_agent.state import AgentState
from research_agent.time_window import resolve_goal_window
from research_agent.tools.registry import ToolRegistry
from research_agent.tools.url_fetch import FetchResponse, URLFetchTool
from research_agent.tools.web_search import WebSearchTool
from research_agent.tools.calculator import CalculatorTool
from research_agent.trace_renderer import TraceRenderer


SOURCE_URL = "https://research.example.org/rag-update"


class FakePlanner:
    def __init__(self) -> None:
        self.goal: Goal | None = None

    def propose(
        self,
        goal: Goal,
        context=None,
        *,
        on_retry: Callable[[str], None] | None = None,
    ) -> Plan:
        self.goal = goal
        assert context["requested_window_start"]
        return Plan(
            goal_id=goal.goal_id,
            steps=[
                PlanStep(
                    id="search",
                    objective="Search for recent RAG research",
                    tool_name=ToolName.WEB_SEARCH,
                    input=WebSearchInput(query="recent RAG research", max_results=2),
                    expected_output="Candidate research URLs",
                    dependencies=[],
                    status=StepStatus.PENDING,
                ),
                PlanStep(
                    id="fetch",
                    objective="Fetch the provided public research page",
                    tool_name=ToolName.URL_FETCH,
                    input=URLFetchInput(url=SOURCE_URL),
                    expected_output="Extracted source content",
                    dependencies=["search"],
                    status=StepStatus.PENDING,
                ),
            ],
        )


class FakeSearchProvider:
    def search(self, search_input: WebSearchInput) -> SearchResults:
        return SearchResults(
            results=[
                SearchResult(
                    title="RAG research update",
                    url=SOURCE_URL,
                    snippet="A recent research update.",
                    source="research.example.org",
                )
            ]
        )


class EvidenceSummaryLLM:
    def generate(self, operation: str, payload: dict, expected_schema: str) -> LLMResponse:
        assert operation == "research_summary"
        first_evidence_id = payload["evidence"][0]["evidence_id"]
        content = json.dumps(
            {
                "findings": [
                    {
                        "finding_id": "rag-update",
                        "title": "A recent RAG update was reported",
                        "summary": "The fetched source describes the stated RAG update.",
                        "evidence_ids": [first_evidence_id],
                    }
                ]
            }
        )
        return LLMResponse(content=content, provider="fake")


def make_controller(logger: EventLogger | None = None) -> tuple[AgentController, EventLogger, FakePlanner]:
    event_logger = logger or EventLogger()
    planner = FakePlanner()
    registry = ToolRegistry(
        [
            WebSearchTool(provider=FakeSearchProvider()),
            URLFetchTool(
                transport=lambda url, timeout, response_limit, text_limit: FetchResponse(
                    status_code=200,
                    content_type="text/html",
                    charset="utf-8",
                    final_url=url,
                    body=(
                        b"<html><head><title>RAG research update</title></head>"
                        b"<body><p>This source describes a recent retrieval augmented generation "
                        b"research update, its method, and its reported evaluation results.</p></body></html>"
                    ),
                ),
                url_validator=lambda url: url,
            ),
            CalculatorTool(),
        ]
    )
    evidence_store = EvidenceStore()
    summary_client = EvidenceSummaryLLM()
    report_generator = ReportGenerator(summary_client, evidence_store, event_logger)
    execution_engine = ExecutionEngine(registry, event_logger=event_logger)
    controller = AgentController(
        planner=planner,
        plan_validator=PlanValidator(),
        execution_engine=execution_engine,
        registry=registry,
        evidence_store=evidence_store,
        report_generator=report_generator,
        event_logger=event_logger,
        clock=lambda: datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
        execution_id_factory=uuid4,
    )
    return controller, event_logger, planner


def test_controller_runs_planning_execution_evidence_and_report_offline() -> None:
    rendered: list[str] = []
    renderer = TraceRenderer()
    logger = EventLogger(sink=lambda event: rendered.append(renderer.render_event(event) or ""))
    controller, event_logger, planner = make_controller(logger)

    report = controller.run(f"Research RAG developments from {SOURCE_URL} in the last 7 days")

    assert report.status.value == "completed"
    assert report.execution_summary.steps_total == 2
    assert report.execution_summary.steps_completed == 2
    assert len(report.evidence) == 1
    assert report.evidence[0].source_url == SOURCE_URL
    assert report.findings[0].evidence_ids == [report.evidence[0].evidence_id]
    assert planner.goal is not None
    assert planner.goal.requested_window is not None
    assert (planner.goal.requested_window.end - planner.goal.requested_window.start).days == 7

    event_types = [event.event_type for event in event_logger.events]
    assert event_types.index(EventType.GOAL_RECEIVED) < event_types.index(EventType.PLAN_CREATED)
    assert event_types.index(EventType.PLAN_CREATED) < event_types.index(EventType.PLAN_VALIDATED)
    assert event_types.index(EventType.PLAN_VALIDATED) < event_types.index(EventType.STEP_STARTED)
    assert event_types.index(EventType.SYNTHESIS_STARTED) < event_types.index(EventType.FINAL_REPORT_CREATED)
    assert event_types[-1] is EventType.EXECUTION_COMPLETED
    assert "[GOAL]" in rendered[0]
    assert any("[PLAN]" in line for line in rendered)
    assert any("✓ fetch" in line for line in rendered)
    assert any("rank" in limitation.lower() for limitation in report.limitations)


def test_controller_resolves_discovered_url_without_planner_knowing_it() -> None:
    controller, _, _ = make_controller()

    class ReferencePlanner(FakePlanner):
        def propose(self, goal, context=None, *, on_retry=None):
            plan = super().propose(goal, context, on_retry=on_retry)
            plan.steps[1].input = SearchResultReference(search_step_id="search", result_index=0)
            return plan

    controller._planner = ReferencePlanner()
    report = controller.run("Research recent RAG developments")
    assert report.status.value == "completed"
    assert report.evidence[0].source_url == SOURCE_URL
    assert report.execution_summary.steps_completed == 2


def test_missing_search_result_reference_fails_without_fetch_dispatch() -> None:
    controller, logger, _ = make_controller()

    class ReferencePlanner(FakePlanner):
        def propose(self, goal, context=None, *, on_retry=None):
            plan = super().propose(goal, context, on_retry=on_retry)
            plan.steps[1].input = SearchResultReference(search_step_id="search", result_index=1)
            return plan

    controller._planner = ReferencePlanner()
    report = controller.run("Research recent RAG developments")
    assert report.status.value == "failed"
    assert report.execution_summary.steps_failed == 1
    assert not any(e.event_type == EventType.TOOL_CALL_STARTED and e.step_id == "fetch"
                   for e in logger.events)


def test_controller_returns_structured_report_when_planning_fails() -> None:
    controller, event_logger, _ = make_controller()

    class BrokenPlanner:
        def propose(
            self,
            goal: Goal,
            context=None,
            *,
            on_retry: Callable[[str], None] | None = None,
        ) -> Plan:
            raise PlannerOutputError(attempts=2, reason="invalid schema")

    controller._planner = BrokenPlanner()
    report = controller.run("Research RAG")

    assert report.status.value == "failed"
    assert report.plan == []
    assert report.execution_summary.steps_total == 0
    assert report.failures[0].category.value == "invalid_response"
    assert "validation: invalid schema" in report.failures[0].message
    assert event_logger.events[-1].event_type is EventType.EXECUTION_COMPLETED
    assert EventType.TOOL_CALL_STARTED not in [event.event_type for event in event_logger.events]


def test_rate_limit_exhaustion_is_reported_with_wait_and_no_tools() -> None:
    controller, logger, _ = make_controller()
    waits = []
    class LimitedClient:
        def generate(self, *args):
            raise GroqLLMError("http_429_rate_limit_exceeded", retryable=True, retry_after_seconds=4)
    controller._planner = Planner(LimitedClient(), controller._registry, sleep=waits.append)
    report = controller.run("Research RAG")
    assert waits == [4]
    assert report.status.value == "failed"
    assert report.failures[0].category.value == "rate_limit"
    assert report.failures[0].retryability.value == "retryable"
    assert "attempts: 2" in report.failures[0].message
    assert "quota" in report.limitations[0].lower()
    retries = [e for e in logger.events if e.event_type == EventType.RETRY_ATTEMPTED]
    assert len(retries) == 1
    trace = TraceRenderer().render_event(retries[0])
    assert "waiting 4s" in trace
    assert trace.count("Planner retry scheduled") == 1
    assert EventType.TOOL_CALL_STARTED not in [e.event_type for e in logger.events]


def test_window_resolution_defaults_and_parses_explicit_ranges() -> None:
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    default_window, defaulted = resolve_goal_window("Research RAG", now)
    assert defaulted is True
    assert (default_window.end - default_window.start).days == 7

    explicit_window, explicit_defaulted = resolve_goal_window(
        "Research RAG from 2026-09-01 to 2026-09-10", now
    )
    assert explicit_defaulted is False
    assert explicit_window.start.date().isoformat() == "2026-09-01"
    assert explicit_window.end.date().isoformat() == "2026-09-10"


def test_engine_refuses_fetch_urls_absent_from_goal_or_search_results() -> None:
    fetched: list[str] = []
    goal = Goal(text="Research current RAG work", run_started_at=utc_now())
    plan = Plan(
        goal_id=goal.goal_id,
        steps=[
            PlanStep(
                id="fetch",
                objective="Fetch a proposed page",
                tool_name=ToolName.URL_FETCH,
                input=URLFetchInput(url=SOURCE_URL),
                expected_output="Page content",
                dependencies=[],
                status=StepStatus.PENDING,
            )
        ],
    )
    fetch_tool = URLFetchTool(
        transport=lambda url, timeout, response_limit, text_limit: (
            fetched.append(url) or FetchResponse(200, "text/plain", "utf-8", url, b"content")
        ),
        url_validator=lambda url: url,
    )
    registry = ToolRegistry([fetch_tool])
    state = AgentState.for_goal(goal, uuid4())
    state.transition(RunState.PLANNING)
    state.transition(RunState.PLAN_VALIDATION)
    validated = PlanValidator().validate(goal, plan, state, registry)
    assert isinstance(validated, Failure)

    # Even a caller bypassing PlanValidator cannot dispatch an unauthorized URL.
    validated = ValidatedPlan(plan=plan, validator_version="test-bypass")

    result = ExecutionEngine(registry).execute(validated, state)

    assert fetched == []
    assert result.step_statuses["fetch"] is StepStatus.FAILED
    assert any(failure.category.value == "unsafe_url" for failure in result.failures)
