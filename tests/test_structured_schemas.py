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
    Finding,
    ReportExecutionSummary,
    ReportPlanStep,
    ReportStatus,
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
        supports=["development-1"],
    )
    evidence = Evidence(
        evidence_id=evidence_id,
        goal_id=goal.goal_id,
        step_id="fetch",
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
        status=ReportStatus.COMPLETED,
        goal=goal.text,
        plan=[ReportPlanStep(
            id=step.id,
            objective=step.objective,
            tool_name=step.tool_name,
            status=StepStatus.SUCCEEDED,
        )],
        execution_summary=ReportExecutionSummary(
            steps_total=1, steps_completed=1, steps_failed=0, retries=0
        ),
        evidence=[evidence],
        findings=[Finding(
            finding_id="development-1",
            title="A research development",
            summary="The source reports a research development.",
            evidence_ids=[evidence_id],
        )],
        sources=[citation],
        recoveries=[recovery],
        failures=[failure],
    )

    assert result.output is not None
    assert evidence.verification is EvidenceVerification.VERIFIED
    assert report.plan[0].status is StepStatus.SUCCEEDED
    assert report.model_dump(mode="json")["plan"][0]["id"] == "search"
    assert report.model_dump(mode="json")["evidence"][0]["step_id"] == "fetch"
    assert report.to_json().startswith("{")
    assert "## Findings" in report.to_markdown()
