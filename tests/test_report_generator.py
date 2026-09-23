from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from research_agent.evidence_store import DuplicateEvidenceError, EvidenceStore
from research_agent.models import (
    Evidence,
    EvidenceVerification,
    Failure,
    FailureCategory,
    FailureOrigin,
    Goal,
    LLMResponse,
    Plan,
    PlanStep,
    Retryability,
    ReportStatus,
    RunState,
    SourceType,
    StepStatus,
    ToolName,
    WebSearchInput,
    utc_now,
)
from research_agent.report_generator import ReportGenerator
from research_agent.state import AgentState


class FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, dict, str]] = []

    def generate(self, operation: str, payload: dict, expected_schema: str) -> LLMResponse:
        self.calls.append((operation, payload, expected_schema))
        return LLMResponse(content=self.content, provider="fake")


def context() -> tuple[Goal, Plan, AgentState]:
    goal = Goal(
        text="Research developments in retrieval-augmented generation",
        run_started_at=utc_now(),
    )
    step = PlanStep(
        id="search",
        objective="Find and fetch evidence about recent RAG work",
        tool_name=ToolName.WEB_SEARCH,
        input=WebSearchInput(query="recent RAG research", max_results=3),
        expected_output="Evidence-backed sources",
        dependencies=[],
        status=StepStatus.PENDING,
    )
    plan = Plan(goal_id=goal.goal_id, steps=[step])
    state = AgentState.for_goal(goal, uuid4())
    state.active_plan = plan
    state.step_statuses = {step.id: StepStatus.SUCCEEDED}
    state.retry_counts = {step.id: 0}
    return goal, plan, state


def evidence_for(goal: Goal, *, verification: EvidenceVerification = EvidenceVerification.VERIFIED) -> Evidence:
    return Evidence(
        goal_id=goal.goal_id,
        step_id="fetch-source",
        source_url="https://research.example.org/rag-paper",
        title="A verified RAG research paper",
        publisher="Research Institute",
        source_type=SourceType.PRIMARY,
        source_group_id="research-institute",
        retrieved_at=utc_now(),
        supporting_text="The paper describes a retrieval method and its evaluated results.",
        supports=["retrieval-method"],
        verification=verification,
    )


def synthesis_content(evidence_id: str) -> str:
    return json.dumps(
        {
            "findings": [
                {
                    "finding_id": "retrieval-method",
                    "title": "A retrieval method was evaluated",
                    "summary": "The paper reports an evaluation of its retrieval method.",
                    "evidence_ids": [evidence_id],
                }
            ]
        }
    )


def test_successful_report_has_json_markdown_and_ledger_only_sources() -> None:
    goal, plan, state = context()
    store = EvidenceStore()
    evidence = evidence_for(goal)
    stored_id = store.add(evidence)
    llm = FakeLLM(synthesis_content(stored_id))

    report = ReportGenerator(llm, store).generate(goal, plan, state)
    payload = json.loads(report.to_json())
    markdown = report.to_markdown()

    assert report.status is ReportStatus.COMPLETED
    assert set(payload) == {
        "goal", "status", "plan", "execution_summary", "failures", "recoveries",
        "evidence", "findings", "limitations", "sources",
    }
    assert payload["execution_summary"] == {
        "steps_total": 1,
        "steps_completed": 1,
        "steps_failed": 0,
        "retries": 0,
    }
    assert payload["sources"][0]["url"] == evidence.source_url
    assert payload["evidence"][0]["step_id"] == "fetch-source"
    assert llm.calls[0][0] == "research_summary"
    assert "## Findings" in markdown
    assert "Generated synthesis" in markdown
    assert "Observed information collected" in markdown
    assert "## Limitations" in markdown
    assert "## Sources" in markdown


def test_failed_step_is_explicit_in_summary_failures_and_limitations() -> None:
    goal, plan, state = context()
    state.step_statuses["search"] = StepStatus.FAILED
    failure = Failure(
        category=FailureCategory.TIMEOUT,
        origin=FailureOrigin.TOOL,
        retryability=Retryability.NON_RETRYABLE,
        run_id=state.run_id,
        step_id="search",
        message="Search provider remained unavailable.",
        occurred_at=utc_now(),
    )
    state.failures.append(failure)
    store = EvidenceStore()
    evidence = evidence_for(goal)
    store.add(evidence)
    llm = FakeLLM(synthesis_content(str(evidence.evidence_id)))

    report = ReportGenerator(llm, store).generate(goal, plan, state)

    assert report.status is ReportStatus.PARTIAL
    assert report.execution_summary.steps_failed == 1
    assert report.failures[0].message == failure.message
    assert any("did not complete" in item for item in report.limitations)


def test_missing_verified_evidence_skips_synthesis_and_states_limitation() -> None:
    goal, plan, state = context()
    llm = FakeLLM('{"findings": []}')
    report = ReportGenerator(llm, EvidenceStore()).generate(goal, plan, state)

    assert report.status is ReportStatus.FAILED
    assert report.findings == []
    assert report.evidence == []
    assert report.sources == []
    assert llm.calls == []
    assert any("no verified collected evidence" in item for item in report.limitations)
    assert "No evidence was collected." in report.to_markdown()


def test_unverified_evidence_is_observed_but_never_used_for_findings() -> None:
    goal, plan, state = context()
    store = EvidenceStore()
    store.add(evidence_for(goal, verification=EvidenceVerification.CANDIDATE))
    llm = FakeLLM('{"findings": []}')

    report = ReportGenerator(llm, store).generate(goal, plan, state)

    assert report.status is ReportStatus.FAILED
    assert report.evidence[0].verification is EvidenceVerification.CANDIDATE
    assert report.findings == []
    assert llm.calls == []


def test_duplicate_evidence_add_is_idempotent_and_conflicting_id_is_rejected() -> None:
    goal, _, _ = context()
    store = EvidenceStore()
    evidence = evidence_for(goal)

    first_id = store.add(evidence)
    duplicate_id = store.add(evidence.model_copy(deep=True))

    assert first_id == duplicate_id
    assert len(store.for_goal(goal.goal_id)) == 1
    changed = evidence.model_copy(update={"title": "Conflicting title"})
    with pytest.raises(DuplicateEvidenceError):
        store.add(changed)


def test_malformed_evidence_is_rejected_before_it_enters_the_store() -> None:
    store = EvidenceStore()
    with pytest.raises(ValidationError):
        store.add(
            {
                "source_url": "file:///private/source.txt",
                "title": "",
                "source_type": "primary",
                "source_group_id": "source",
                "retrieved_at": datetime.now(timezone.utc),
                "supporting_text": "untrusted",
            }
        )
    assert store.all() == []


def test_model_cannot_supply_source_records_or_uncollected_citations() -> None:
    goal, plan, state = context()
    evidence = evidence_for(goal)
    store = EvidenceStore()
    store.add(evidence)
    invented_id = str(uuid4())
    llm = FakeLLM(
        json.dumps(
            {
                "findings": [
                    {
                        "finding_id": "invented",
                        "title": "Unsupported result",
                        "summary": "Claim from a made-up source",
                        "evidence_ids": [invented_id],
                    }
                ],
                "sources": [
                    {"url": "https://invented.example", "title": "Invented source"}
                ],
            }
        )
    )

    report = ReportGenerator(llm, store).generate(goal, plan, state)

    assert report.status is ReportStatus.PARTIAL
    assert report.findings == []
    assert [source.url for source in report.sources] == [evidence.source_url]
    assert report.failures[0].category is FailureCategory.SYNTHESIS_INVALID


def test_synthesis_finding_cannot_smuggle_in_a_fabricated_url() -> None:
    goal, plan, state = context()
    evidence = evidence_for(goal)
    store = EvidenceStore()
    store.add(evidence)
    payload = json.loads(synthesis_content(str(evidence.evidence_id)))
    payload["findings"][0]["summary"] = "See https://made-up.example for proof."

    report = ReportGenerator(FakeLLM(json.dumps(payload)), store).generate(
        goal, plan, state
    )

    assert report.findings == []
    assert report.sources[0].url == evidence.source_url
    assert report.failures[0].category is FailureCategory.SYNTHESIS_INVALID

