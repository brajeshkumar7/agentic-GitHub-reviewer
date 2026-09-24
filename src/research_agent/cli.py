"""Command-line entry point for one controller-driven research run."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO
from uuid import uuid4

from pydantic import ValidationError

from research_agent.config import AgentSettings
from research_agent.controller import AgentController
from research_agent.evidence_store import EvidenceStore
from research_agent.event_logger import EventLogger, JsonlEventLogger
from research_agent.execution_engine import ExecutionEngine
from research_agent.models import (
    ExecutionEvent,
    EventOutcome,
    EventType,
    Failure,
    FailureCategory,
    FailureOrigin,
    FinalReport,
    Goal,
    Plan,
    ReportExecutionSummary,
    ReportStatus,
    Retryability,
    utc_now,
)
from research_agent.plan_validator import PlanValidator
from research_agent.planner import Planner
from research_agent.providers.groq import GroqLLMClient
from research_agent.report_generator import ReportGenerator
from research_agent.state import AgentState
from research_agent.tools.calculator import CalculatorTool
from research_agent.tools.registry import ToolRegistry
from research_agent.tools.url_fetch import URLFetchTool
from research_agent.tools.web_search import WebSearchTool
from research_agent.trace_renderer import TraceRenderer


def render_trace(plan: Plan, events: list[ExecutionEvent]) -> str:
    """Return the public plan/action trace without model reasoning."""
    return TraceRenderer().render(plan, events)


def write_trace(
    plan: Plan,
    events: list[ExecutionEvent],
    stream: TextIO = sys.stderr,
) -> None:
    """Write a structured plan and its public execution trace to stderr by default."""
    print(render_trace(plan, events), file=stream)


def build_default_controller(
    settings: AgentSettings,
    event_logger: EventLogger,
) -> AgentController:
    """Wire the approved provider, tools, stateful engine, evidence, and report components."""
    registry = ToolRegistry(
        [
            WebSearchTool(),
            URLFetchTool(),
            CalculatorTool(),
        ]
    )
    llm_client = GroqLLMClient(settings)
    evidence_store = EvidenceStore()
    planner = Planner(llm_client, registry)
    report_generator = ReportGenerator(llm_client, evidence_store, event_logger)

    def replan(goal: Goal, state: AgentState, failure: Failure) -> Plan:
        current_plan = state.active_plan
        if current_plan is None:
            return planner.propose(goal)

        def record_retry(reason: str) -> None:
            for event_type, status, summary in (
                (
                    EventType.RECOVERY_STARTED,
                    EventOutcome.STARTED,
                    "Applying a bounded planner retry during replanning.",
                ),
                (
                    EventType.RETRY_ATTEMPTED,
                    EventOutcome.SCHEDULED,
                    "A bounded replan output retry was scheduled.",
                ),
            ):
                event = state.record_event(
                    event_type,
                    outcome=status,
                    summary=summary,
                    metadata={"reason": reason},
                )
                event_logger.emit(event)

        proposal = planner.propose(
            goal,
            {
                "replan_request": "Return exactly one replacement step for the failed work.",
                "failed_step_id": failure.step_id,
                "failure_category": failure.category.value,
                "current_plan": current_plan.model_dump(mode="json"),
                "already_completed_steps": [
                    step_id
                    for step_id, status in state.step_statuses.items()
                    if status.value == "SUCCEEDED"
                ],
            },
            on_retry=record_retry,
        )
        if len(proposal.steps) != 1:
            return proposal
        replacement = proposal.steps[0]
        digest = hashlib.sha256((failure.step_id or "run").encode()).hexdigest()[:8]
        replacement = replacement.model_copy(
            update={
                "id": f"recovery-{digest}",
                "dependencies": [],
                "recovery_of_step_id": failure.step_id,
            }
        )
        return Plan.model_validate(
            {
                **proposal.model_dump(),
                "revision": current_plan.revision + 1,
                "replaces_plan_id": current_plan.plan_id,
                "steps": [replacement.model_dump()],
            }
        )

    execution_engine = ExecutionEngine(
        registry,
        event_logger=event_logger,
        settings=settings,
        replanner=replan,
    )
    return AgentController(
        planner=planner,
        plan_validator=PlanValidator(),
        execution_engine=execution_engine,
        registry=registry,
        evidence_store=evidence_store,
        report_generator=report_generator,
        event_logger=event_logger,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-agent",
        description="Autonomous Research Intelligence Agent",
    )
    parser.add_argument("goal", help="natural-language research goal")
    parser.add_argument(
        "--events-jsonl",
        type=Path,
        help="append structured execution events to this JSONL file",
    )
    return parser


def _trace_sink(event: ExecutionEvent) -> None:
    rendered = TraceRenderer().render_event(event)
    if rendered:
        print(rendered, file=sys.stderr, flush=True)


def _setup_failure_report(
    goal_text: str,
    error_type: str,
    category: FailureCategory = FailureCategory.AUTH_CONFIG,
) -> FinalReport:
    now = utc_now()
    goal = Goal(text=goal_text, run_started_at=now)
    failure = Failure(
        category=category,
        origin=FailureOrigin.EXECUTOR,
        retryability=Retryability.NON_RETRYABLE,
        run_id=uuid4(),
        message=f"Application setup failed ({error_type}); no external tools were run.",
        occurred_at=now,
    )
    return FinalReport(
        status=ReportStatus.FAILED,
        goal=goal.text,
        execution_summary=ReportExecutionSummary(
            steps_total=0,
            steps_completed=0,
            steps_failed=0,
            retries=0,
        ),
        failures=[failure],
        limitations=[failure.message],
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.goal.strip():
        parser.error("a non-empty research goal is required")

    logger: EventLogger
    try:
        settings = AgentSettings.from_env()
    except (ValidationError, ValueError) as error:
        report = _setup_failure_report(args.goal, type(error).__name__)
    else:
        try:
            logger = (
                JsonlEventLogger(args.events_jsonl, sink=_trace_sink)
                if args.events_jsonl is not None
                else EventLogger(sink=_trace_sink)
            )
            controller = build_default_controller(settings, logger)
            report = controller.run(args.goal)
        except OSError as error:
            report = _setup_failure_report(
                args.goal, type(error).__name__, FailureCategory.STATE_INVARIANT
            )
        except Exception as error:
            report = _setup_failure_report(
                args.goal, type(error).__name__, FailureCategory.STATE_INVARIANT
            )

    print(report.to_json())
    return 0 if report.status is ReportStatus.COMPLETED else 1


if __name__ == "__main__":
    raise SystemExit(main())
