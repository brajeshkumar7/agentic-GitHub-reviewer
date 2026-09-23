"""Evidence-grounded synthesis with deterministic JSON and Markdown outputs."""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field

from research_agent.evidence_store import EvidenceStore
from research_agent.interfaces import LLMClient
from research_agent.models import (
    Evidence,
    EvidenceVerification,
    Failure,
    FailureCategory,
    FailureOrigin,
    FinalReport,
    Finding,
    Goal,
    Plan,
    ReportStatus,
    ReportExecutionSummary,
    ReportPlanStep,
    Retryability,
    RunState,
    SourceCitation,
    StepStatus,
    StrictModel,
    ToolCallKind,
    utc_now,
)
from research_agent.state import AgentState


class ReportSynthesisDraft(StrictModel):
    """The only content the synthesis model may generate for the report."""

    findings: list[Finding] = Field(max_length=3)


class ReportGenerator:
    """Build a validated report; evidence and source metadata stay application-owned."""

    def __init__(self, llm_client: LLMClient, evidence_store: EvidenceStore) -> None:
        self._llm_client = llm_client
        self._evidence_store = evidence_store

    def generate(self, goal: Goal, plan: Plan, state: AgentState) -> FinalReport:
        """Synthesize verified ledger entries and return a dual-format report model."""
        if plan.goal_id != goal.goal_id or state.goal.goal_id != goal.goal_id:
            return self._fatal_report(
                goal, plan, state, "Report inputs do not belong to the same goal."
            )

        evidence = self._evidence_store.for_goal(goal.goal_id)
        verified = [
            item for item in evidence
            if item.verification == EvidenceVerification.VERIFIED
        ]
        failures = self._unique_failures(state.failures)
        plan_steps = [
            ReportPlanStep(
                id=step.id,
                objective=step.objective,
                tool_name=step.tool_name,
                status=state.step_statuses.get(step.id, step.status),
                dependencies=step.dependencies,
            )
            for step in plan.steps
        ]
        summary = ReportExecutionSummary(
            steps_total=len(plan_steps),
            steps_completed=sum(step.status == StepStatus.SUCCEEDED for step in plan_steps),
            steps_failed=sum(step.status == StepStatus.FAILED for step in plan_steps),
            retries=sum(call.kind == ToolCallKind.RETRY for call in state.tool_calls),
        )
        sources = [self._source_from_evidence(item) for item in evidence]
        limitations: list[str] = []
        draft: ReportSynthesisDraft | None = None

        if not verified:
            limitations.append(
                "Insufficient evidence: no verified collected evidence was available; findings were omitted."
            )
        else:
            try:
                draft = self._synthesize(goal, verified)
            except Exception as error:
                failure = Failure(
                    category=FailureCategory.SYNTHESIS_INVALID,
                    origin=FailureOrigin.REPORT,
                    retryability=Retryability.NON_RETRYABLE,
                    run_id=state.run_id,
                    message=f"Final synthesis failed validation or provider processing ({type(error).__name__}).",
                    occurred_at=utc_now(),
                )
                failures.append(failure)
                limitations.append(
                    "Final synthesis was unavailable; verified evidence is listed, but findings were not generated."
                )

        findings = draft.findings if draft is not None else []
        if verified and not findings:
            limitations.append(
                "The synthesis returned no supported findings from the available verified evidence."
            )
        if summary.steps_failed or summary.steps_completed < summary.steps_total:
            limitations.append("One or more planned steps did not complete successfully.")

        if not verified:
            status = ReportStatus.FAILED
        elif state.lifecycle_state == RunState.FAILED:
            status = ReportStatus.FAILED
        elif (
            state.step_failures
            or summary.steps_failed
            or summary.steps_completed < summary.steps_total
        ):
            status = ReportStatus.PARTIAL
        elif draft is None or not findings:
            status = ReportStatus.PARTIAL
        else:
            status = ReportStatus.COMPLETED

        return FinalReport(
            goal=goal.text,
            # Status is an application decision, never supplied by the model.
            status=status,
            plan=plan_steps,
            execution_summary=summary,
            failures=failures,
            recoveries=state.recovery_history,
            evidence=evidence,
            findings=findings,
            limitations=limitations,
            sources=sources,
        )

    def _synthesize(self, goal: Goal, evidence: list[Evidence]) -> ReportSynthesisDraft:
        schema = ReportSynthesisDraft.model_json_schema()
        payload: dict[str, Any] = {
            "instruction": (
                "Create up to three concise findings supported only by the supplied verified evidence. "
                "Cite evidence IDs in every finding. Do not create sources, URLs, citations, or unsupported claims. "
                "Return JSON matching the schema."
            ),
            "goal": goal.text,
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "schema": schema,
        }
        response = self._llm_client.generate(
            "research_summary", payload, json.dumps(schema, sort_keys=True)
        )
        draft = ReportSynthesisDraft.model_validate_json(response.content)
        verified_ids = {item.evidence_id for item in evidence}
        if any(
            evidence_id not in verified_ids
            for finding in draft.findings
            for evidence_id in finding.evidence_ids
        ):
            raise ValueError("synthesis referenced evidence outside the verified ledger")
        return draft

    @staticmethod
    def _source_from_evidence(evidence: Evidence) -> SourceCitation:
        return SourceCitation(
            evidence_id=evidence.evidence_id,
            url=evidence.source_url,
            title=evidence.title,
            publisher=evidence.publisher,
            source_type=evidence.source_type,
            published_at=evidence.published_at,
            retrieved_at=evidence.retrieved_at,
            supports=evidence.supports,
        )

    @staticmethod
    def _unique_failures(failures: list[Failure]) -> list[Failure]:
        unique: dict[Any, Failure] = {}
        for failure in failures:
            unique.setdefault(failure.failure_id, failure)
        return list(unique.values())

    @staticmethod
    def _fatal_report(
        goal: Goal, plan: Plan, state: AgentState, message: str
    ) -> FinalReport:
        failure = Failure(
            category=FailureCategory.STATE_INVARIANT,
            origin=FailureOrigin.REPORT,
            retryability=Retryability.NON_RETRYABLE,
            run_id=state.run_id,
            message=message,
            occurred_at=utc_now(),
        )
        report_steps = [
            ReportPlanStep(
                id=step.id,
                objective=step.objective,
                tool_name=step.tool_name,
                status=state.step_statuses.get(step.id, StepStatus.PENDING),
                dependencies=step.dependencies,
            )
            for step in plan.steps
        ]
        return FinalReport(
            goal=goal.text,
            status=ReportStatus.FAILED,
            plan=report_steps,
            execution_summary=ReportExecutionSummary(
                steps_total=len(report_steps),
                steps_completed=sum(step.status == StepStatus.SUCCEEDED for step in report_steps),
                steps_failed=sum(step.status == StepStatus.FAILED for step in report_steps),
                retries=sum(call.kind == ToolCallKind.RETRY for call in state.tool_calls),
            ),
            failures=[*ReportGenerator._unique_failures(state.failures), failure],
            recoveries=state.recovery_history,
            evidence=[],
            findings=[],
            limitations=[message],
            sources=[],
        )
