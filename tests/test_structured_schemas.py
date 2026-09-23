from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from research_agent.models import (
    Calculation,
    CalculatorOperation,
    EventOutcome,
    EventType,
    ExecutionEvent,
    ExecutionSummary,
    Evidence,
    EvidenceVerification,
    Failure,
    FailureCategory,
    FailureOrigin,
    FinalReport,
    Goal,
    Plan,
    PlanStep,
    RecoveryAction,
    RecoveryKind,
    RecoveryReason,
    ResearchBrief,
    Retryability,
    RunState,
    SourceCitation,
    SourceType,
    StepStatus,
    ToolCall,
    ToolCallKind,
    ToolName,
    ToolResult,
    ToolResultStatus,
    WebSearchInput,
)


def test_all_assignment_boundary_schemas_instantiate_and_validate() -> None:
    now = datetime.now(timezone.utc)
    goal = Goal(text="Research current RAG work", run_started_at=now)
    step = PlanStep(
        id="search",
        objective="Find current RAG sources",
        tool_name=ToolName.WEB_SEARCH,
        input=WebSearchInput(query="current RAG", max_results=2),
        expected_output="Candidate source list",
        dependencies=[],
        status=StepStatus.PENDING,
    )
    plan = Plan(goal_id=goal.goal_id, steps=[step])
    run_id = uuid4()
    call = ToolCall(
        run_id=run_id,
        step_id=step.id,
        tool_name=step.tool_name,
        arguments=step.input,
        attempt=1,
        kind=ToolCallKind.PRIMARY,
        created_at=now,
    )
    result = ToolResult(
        call_id=call.call_id,
        status=ToolResultStatus.SUCCEEDED,
        output=Calculation(
            operation=CalculatorOperation.ADD,
            operands=[Decimal("1"), Decimal("2")],
            result=Decimal("3"),
        ),
        started_at=now,
        finished_at=now,
    )
    evidence_id = uuid4()
    citation = SourceCitation(
        evidence_id=evidence_id,
        url="https://example.org/research",
        title="Research report",
        publisher="Example Institute",
        source_type=SourceType.PRIMARY,
        retrieved_at=now,
    )
    evidence = Evidence(
        evidence_id=evidence_id,
        source_url=citation.url,
        title=citation.title,
        publisher=citation.publisher,
        source_type=SourceType.PRIMARY,
        source_group_id="example-institute",
        retrieved_at=now,
        supporting_text="The report describes a research development.",
        supports=["development-1"],
        verification=EvidenceVerification.VERIFIED,
    )
    failure = Failure(
        category=FailureCategory.TIMEOUT,
        origin=FailureOrigin.TOOL,
        retryability=Retryability.RETRYABLE,
        run_id=run_id,
        message="Request timed out",
        occurred_at=now,
    )
    recovery = RecoveryAction(
        failure_id=failure.failure_id,
        kind=RecoveryKind.RETRY,
        target_step_id=step.id,
        reason_code=RecoveryReason.TRANSIENT,
        selected_at=now,
    )
    event = ExecutionEvent(
        run_id=run_id,
        sequence=1,
        timestamp=now,
        event_type=EventType.PLAN_CREATED,
        state=RunState.PLANNING,
        outcome=EventOutcome.SUCCEEDED,
        summary="Validated plan proposed",
    )
    report = FinalReport(
        run_id=run_id,
        status=RunState.COMPLETED,
        goal=goal.text,
        run_started_at=now,
        run_finished_at=now,
        research_brief=ResearchBrief(
            topic="RAG",
            time_window_start=now,
            time_window_end=now,
            summary="A concise summary.",
            comparison="The sources are comparable.",
            conclusion="More research may be useful.",
        ),
        sources=[citation],
        plan=plan,
        execution=ExecutionSummary(events=[event], recovered_failures=[recovery]),
        failures=[failure],
    )

    assert result.output is not None
    assert evidence.verification is EvidenceVerification.VERIFIED
    assert report.plan.steps[0].status is StepStatus.PENDING
    assert report.model_dump(mode="json")["plan"]["steps"][0]["id"] == "search"
    assert report.model_dump(mode="json", by_alias=True)["plan"]["steps"][0]["step_id"] == "search"
