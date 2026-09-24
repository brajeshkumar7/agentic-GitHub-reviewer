"""Concrete deterministic validation before any future plan execution."""

from __future__ import annotations

from pydantic import ValidationError

from research_agent.interfaces import ToolRegistry
from research_agent.models import (
    Failure,
    FailureCategory,
    FailureOrigin,
    Goal,
    Plan,
    Retryability,
    SearchResultReference,
    ToolName,
    URLFetchInput,
    SearchResults,
    ToolResultStatus,
    ValidatedPlan,
    utc_now,
)
from research_agent.state import AgentState


class PlanValidator:
    """Revalidate proposal invariants and bind a plan to its submitted goal."""

    def validate(
        self,
        goal: Goal,
        proposal: Plan,
        state: AgentState,
        registry: ToolRegistry,
    ) -> ValidatedPlan | Failure:
        try:
            plan = Plan.model_validate(proposal.model_dump())
            registered_names = {item.name for item in registry.metadata()}
            discovered_urls = {
                candidate.url for result in state.tool_results
                if result.status == ToolResultStatus.SUCCEEDED
                and isinstance(result.output, SearchResults)
                for candidate in result.output.results
            }
            for step in plan.steps:
                if step.tool_name not in registered_names:
                    raise ValueError("plan references a tool that is not registered")
                if not isinstance(step.input, SearchResultReference):
                    registry.validate_arguments(step.tool_name.value, step.input)
                    if (isinstance(step.input, URLFetchInput)
                            and step.input.url not in goal.text
                            and step.input.url not in discovered_urls):
                        raise ValueError("fetch requires a search result reference")
                if step.fallback is not None:
                    if step.fallback.tool_name not in registered_names:
                        raise ValueError("fallback references a tool that is not registered")
                    registry.validate_arguments(
                        step.fallback.tool_name.value, step.fallback.arguments
                    )
                    if (isinstance(step.fallback.arguments, URLFetchInput)
                            and step.fallback.arguments.url not in goal.text
                            and step.fallback.arguments.url not in discovered_urls):
                        raise ValueError("fallback fetch URL has no authorized source")
            if plan.goal_id != goal.goal_id:
                raise ValueError("plan goal_id does not match the submitted goal")
            if state.goal.goal_id != goal.goal_id:
                raise ValueError("validator state does not belong to the submitted goal")
            if state.active_plan is None:
                if plan.revision != 1 or plan.replaces_plan_id is not None:
                    raise ValueError("initial plan must be revision 1 without a replaced plan")
            else:
                previous = state.active_plan
                if previous.revision >= 2:
                    raise ValueError("plan revision allowance is exhausted")
                if (
                    plan.revision != previous.revision + 1
                    or plan.replaces_plan_id != previous.plan_id
                ):
                    raise ValueError("revised plan must replace the active plan exactly once")
            return ValidatedPlan(plan=plan, validator_version="phase3-registry")
        except (ValidationError, LookupError, ValueError, TypeError) as error:
            return Failure(
                category=FailureCategory.INVALID_ARGUMENT,
                origin=FailureOrigin.VALIDATOR,
                retryability=Retryability.SEMANTIC,
                run_id=state.run_id,
                message=f"Plan rejected: {type(error).__name__}",
                occurred_at=utc_now(),
            )
