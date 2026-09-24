"""Injectable orchestration for one complete research-agent run."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from research_agent.event_logger import EventLogger
from research_agent.interfaces import (
    EvidenceStore as EvidenceStorePort,
    ExecutionEngine as ExecutionEnginePort,
    PlanValidatorPort,
    PlannerPort,
    ReportGenerator as ReportGeneratorPort,
    ToolRegistry as ToolRegistryPort,
)
from research_agent.models import (
    Evidence,
    EvidenceVerification,
    EventOutcome,
    EventType,
    Failure,
    FailureCategory,
    FailureOrigin,
    FetchedPage,
    FinalReport,
    Goal,
    Plan,
    ReportExecutionSummary,
    ReportPlanStep,
    ReportStatus,
    Retryability,
    RunState,
    SourceType,
    SourceCitation,
    StepStatus,
    ToolCallKind,
    utc_now,
)
from research_agent.planner import PlannerOutputError, PlannerProviderError
from research_agent.time_window import resolve_goal_window
from research_agent.state import AgentState


class AgentController:
    """Coordinate planning, validation, stateful execution, evidence, and reporting."""

    def __init__(
        self,
        *,
        planner: PlannerPort,
        plan_validator: PlanValidatorPort,
        execution_engine: ExecutionEnginePort,
        registry: ToolRegistryPort,
        evidence_store: EvidenceStorePort,
        report_generator: ReportGeneratorPort,
        event_logger: EventLogger,
        clock: Callable[[], datetime] = utc_now,
        execution_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._planner = planner
        self._plan_validator = plan_validator
        self._execution_engine = execution_engine
        self._registry = registry
        self._evidence_store = evidence_store
        self._report_generator = report_generator
        self._event_logger = event_logger
        self._clock = clock
        self._execution_id_factory = execution_id_factory

    def run(self, goal_text: str) -> FinalReport:
        """Run the complete approved pipeline and return one validated final report."""
        started_at = self._clock()
        window, defaulted = resolve_goal_window(goal_text, started_at)
        goal = Goal(
            text=goal_text,
            requested_window=window,
            run_started_at=started_at,
        )
        state = AgentState.for_goal(goal, self._execution_id_factory())
        self._emit(
            state,
            EventType.GOAL_RECEIVED,
            EventOutcome.SUCCEEDED,
            "Research goal accepted.",
            metadata={"goal": goal.text},
        )
        self._transition(state, RunState.PLANNING)

        try:
            proposal = self._planner.propose(
                goal,
                {
                    "requested_window_start": window.start.isoformat(),
                    "requested_window_end": window.end.isoformat(),
                    "tool_policy": "Use only registered tools; search results are leads, fetch pages for evidence.",
                },
                on_retry=lambda reason: self._record_planner_retry(state, reason),
            )
        except (PlannerOutputError, PlannerProviderError) as error:
            rate_limited = isinstance(error, PlannerProviderError) and (
                error.category.startswith("http_429") or error.category == "rate_limited"
            )
            category = (
                FailureCategory.RATE_LIMIT if rate_limited else
                FailureCategory.AUTH_CONFIG
                if isinstance(error, PlannerProviderError)
                and error.category == "missing_configuration"
                else FailureCategory.LLM_ERROR
                if isinstance(error, PlannerProviderError)
                else FailureCategory.INVALID_RESPONSE
            )
            detail = (
                f"Planning failed (provider category: {error.category}; attempts: {error.attempts}); no tools were executed."
                if isinstance(error, PlannerProviderError)
                else f"Planning failed ({type(error).__name__}; attempts: {error.attempts}; validation: {error.reason}); no tools were executed."
            )
            if rate_limited:
                detail += " Groq quota is exhausted. Wait for the quota reset and check your organization's model limits before rerunning."
                if error.retry_after_seconds is not None:
                    detail += f" Provider Retry-After: {error.retry_after_seconds:g}s."
            failure = self._failure(
                state,
                category,
                FailureOrigin.PLANNER,
                detail,
                retryability=(Retryability.RETRYABLE
                    if isinstance(error, PlannerProviderError) and error.retryable
                    else Retryability.NON_RETRYABLE),
            )
            return self._failed_report(goal, state, failure, defaulted=defaulted)
        except Exception as error:
            failure = self._failure(
                state,
                FailureCategory.LLM_ERROR,
                FailureOrigin.PLANNER,
                f"Planning failed unexpectedly ({type(error).__name__}); no tools were executed.",
            )
            return self._failed_report(goal, state, failure, defaulted=defaulted)

        self._emit(
            state,
            EventType.PLAN_CREATED,
            EventOutcome.SUCCEEDED,
            "Structured plan created.",
            metadata={
                "steps": [
                    {
                        "id": step.id,
                        "objective": step.objective,
                        "tool_name": step.tool_name.value,
                    }
                    for step in proposal.steps
                ]
            },
        )
        self._transition(state, RunState.PLAN_VALIDATION)
        validated = self._plan_validator.validate(
            goal, proposal, state, self._registry
        )
        if isinstance(validated, Failure):
            state.failures.append(validated)
            self._emit(
                state,
                EventType.PLAN_REJECTED,
                EventOutcome.REJECTED,
                "Plan failed deterministic validation; no tools were executed.",
            )
            self._transition(state, RunState.FAILED, summary="The plan was rejected.")
            return self._failed_report(goal, state, validated, defaulted=defaulted)

        self._emit(
            state,
            EventType.PLAN_VALIDATED,
            EventOutcome.SUCCEEDED,
            "Plan passed schema, dependency, tool, and argument validation.",
        )
        state = self._execution_engine.execute(validated, state)
        active_plan = state.active_plan or validated.plan
        self._collect_fetched_evidence(goal, state)

        try:
            report = self._report_generator.generate(goal, active_plan, state)
        except Exception as error:
            failure = self._failure(
                state,
                FailureCategory.SYNTHESIS_INVALID,
                FailureOrigin.REPORT,
                f"Report generation failed ({type(error).__name__}).",
            )
            return self._failed_report(goal, state, failure, defaulted=defaulted)

        limitations = list(report.limitations)
        limitations.append(
            "Evidence is verified as successfully retrieved and extracted; source authority ranking and claim-level corroboration are not yet implemented."
        )
        if defaulted:
            limitations.append(
                f"No explicit time window was recognized; the search window defaulted to the seven days ending {window.end.date().isoformat()} UTC."
            )
        report = FinalReport.model_validate(
            {
                **report.model_dump(),
                "limitations": list(dict.fromkeys(limitations)),
            }
        )
        return report

    def _collect_fetched_evidence(
        self,
        goal: Goal,
        state: AgentState,
    ) -> None:
        step_by_call_id = {call.call_id: call.step_id for call in state.tool_calls}
        seen_urls: set[str] = set()
        for result in state.tool_results:
            page = result.output
            if not isinstance(page, FetchedPage):
                continue
            normalized_url = page.final_url.rstrip("/").casefold()
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            host = (urlsplit(page.final_url).hostname or "unknown-source").casefold()
            evidence = Evidence(
                goal_id=goal.goal_id,
                step_id=step_by_call_id.get(result.call_id, "unknown-step"),
                source_url=page.final_url,
                title=page.title or host,
                publisher=page.publisher or host,
                source_type=SourceType.OTHER,
                source_group_id=host,
                published_at=page.published_at,
                retrieved_at=page.retrieved_at,
                supporting_text=page.extracted_text,
                supports=[],
                verification=EvidenceVerification.VERIFIED,
            )
            evidence_id = UUID(self._evidence_store.add(evidence))
            state.evidence_ids.append(evidence_id)
            self._emit(
                state,
                EventType.EVIDENCE_RECORDED,
                EventOutcome.SUCCEEDED,
                "Retrieved page content was added to the evidence ledger.",
                step_id=evidence.step_id,
                metadata={"evidence_id": str(evidence_id), "source_host": host},
            )

    def _failed_report(
        self,
        goal: Goal,
        state: AgentState,
        failure: Failure,
        *,
        defaulted: bool,
    ) -> FinalReport:
        if failure not in state.failures:
            state.failures.append(failure)
        if state.lifecycle_state not in {RunState.FAILED, RunState.COMPLETED, RunState.PARTIAL}:
            self._transition(state, RunState.FAILED, summary=failure.message)
        limitations = [failure.message]
        if failure.origin == FailureOrigin.PLANNER and failure.category == FailureCategory.INVALID_RESPONSE:
            self._emit(
                state,
                EventType.PLAN_REJECTED,
                EventOutcome.REJECTED,
                "Planner output remained invalid after its bounded repair attempt.",
            )
        if defaulted and goal.requested_window is not None:
            limitations.append(
                f"No explicit time window was recognized; the search window defaulted to the seven days ending {goal.requested_window.end.date().isoformat()} UTC."
            )
        report_plan = [
            ReportPlanStep(
                id=step.id,
                objective=step.objective,
                tool_name=step.tool_name,
                status=state.step_statuses.get(step.id, step.status),
                dependencies=step.dependencies,
            )
            for step in (state.active_plan.steps if state.active_plan is not None else [])
        ]
        evidence = self._evidence_store.for_goal(goal.goal_id)
        report = FinalReport(
            status=ReportStatus.FAILED,
            goal=goal.text,
            plan=report_plan,
            execution_summary=ReportExecutionSummary(
                steps_total=len(report_plan),
                steps_completed=sum(item.status == StepStatus.SUCCEEDED for item in report_plan),
                steps_failed=sum(item.status == StepStatus.FAILED for item in report_plan),
                retries=sum(call.kind == ToolCallKind.RETRY for call in state.tool_calls),
            ),
            failures=list(state.failures),
            recoveries=state.recovery_history,
            evidence=evidence,
            findings=[],
            limitations=limitations,
            sources=[
                SourceCitation(
                    evidence_id=item.evidence_id,
                    url=item.source_url,
                    title=item.title,
                    publisher=item.publisher,
                    source_type=item.source_type,
                    published_at=item.published_at,
                    retrieved_at=item.retrieved_at,
                    supports=item.supports,
                )
                for item in evidence
            ],
        )
        self._emit(
            state,
            EventType.FINAL_REPORT_CREATED,
            EventOutcome.FAILED,
            "A structured failure report was created.",
            metadata={"report_status": report.status.value},
        )
        self._emit(
            state,
            EventType.EXECUTION_COMPLETED,
            EventOutcome.COMPLETED,
            "Agent execution ended with a handled failure.",
            metadata={"report_status": report.status.value},
        )
        return report

    @staticmethod
    def _failure(
        state: AgentState,
        category: FailureCategory,
        origin: FailureOrigin,
        message: str,
        *,
        retryability: Retryability = Retryability.NON_RETRYABLE,
    ) -> Failure:
        return Failure(
            category=category,
            origin=origin,
            retryability=retryability,
            run_id=state.run_id,
            message=message,
            occurred_at=utc_now(),
        )

    def _emit(
        self,
        state: AgentState,
        event_type: EventType,
        status: EventOutcome,
        summary: str,
        *,
        step_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        event = state.record_event(
            event_type,
            outcome=status,
            summary=summary,
            step_id=step_id,
            metadata=metadata,
        )
        self._event_logger.emit(event)

    def _record_planner_retry(self, state: AgentState, reason: str) -> None:
        self._emit(
            state,
            EventType.RECOVERY_STARTED,
            EventOutcome.STARTED,
            "Applying the bounded planner retry.",
            metadata={"reason": reason},
        )
        self._emit(
            state,
            EventType.RETRY_ATTEMPTED,
            EventOutcome.SCHEDULED,
            f"Planner retry scheduled: {reason}.",
            metadata={"reason": reason},
        )

    def _transition(
        self,
        state: AgentState,
        target: RunState,
        *,
        summary: str | None = None,
    ) -> None:
        self._event_logger.emit(state.transition(target, summary=summary))


__all__ = ["AgentController"]
