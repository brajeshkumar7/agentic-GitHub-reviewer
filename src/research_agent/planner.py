"""Structured planner with strict local validation and one bounded repair."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from research_agent.interfaces import LLMClient, ToolRegistry
from research_agent.limits import (
    MAX_MODEL_ATTEMPTS,
    MAX_MODEL_RETRY_DELAY_SECONDS,
    MAX_PLAN_STEPS,
    MAX_PLANNER_REPAIR_CHARS,
)
from research_agent.models import Goal, Plan, URLFetchInput
from research_agent.prompts import (
    PLAN_REQUEST_TEMPLATE,
    PLANNER_REPAIR_TEMPLATE,
)
from research_agent.providers.groq import GroqLLMError


class PlannerOutputError(RuntimeError):
    """Controlled failure after the bounded structured-output attempts."""

    def __init__(self, *, attempts: int, reason: str) -> None:
        self.attempts = attempts
        self.reason = reason
        super().__init__(f"planner returned invalid structured output after {attempts} attempts: {reason}")


class PlannerProviderError(RuntimeError):
    """Safe provider failure wrapper; never includes credentials or raw content."""

    def __init__(
        self, *, attempts: int, retryable: bool, category: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.attempts = attempts
        self.retryable = retryable
        self.category = category
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"planner provider failure ({category}) after {attempts} attempt(s)")


class _PlanContractError(ValueError):
    """Application-owned diagnostic code, never model-provided text."""


def _validation_feedback(error: ValueError, schema: dict[str, Any], content: str) -> str:
    """Describe errors without exposing values, custom messages, or unknown keys."""
    if isinstance(error, _PlanContractError):
        return str(error)
    if not isinstance(error, ValidationError):
        return "plan_contract_invalid"
    known_fields: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            known_fields.update(node.get("properties", {}).keys())
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(schema)
    try:
        raw = json.loads(content)
        steps = raw.get("steps", []) if isinstance(raw, dict) else []
    except ValueError:
        steps = []
    branches = {"web_search": "WebSearchInput", "url_fetch": "URLFetchInput",
                "calculator": "CalculatorInput"}
    branch_names = set(branches.values()) | {"SearchResultReference"}
    diagnostics = []
    for item in error.errors(include_input=False, include_context=False, include_url=False):
        location = item["loc"]
        branch = None
        if len(location) >= 4 and isinstance(location[3], str):
            branch = next((name for name in branch_names
                           if location[3] == name or (
                               location[3].startswith("function-after[")
                               and location[3].endswith(f", {name}]"))), None)
        if (len(location) >= 4 and location[0] == "steps"
                and isinstance(location[1], int) and isinstance(steps, list)
                and location[1] < len(steps) and isinstance(steps[location[1]], dict)
                and location[2] in {"input", "arguments"} and branch is not None):
            step = steps[location[1]]
            tool_name = step.get("tool_name")
            selected = branches.get(tool_name) if isinstance(tool_name, str) else None
            arguments = step.get("input", step.get("arguments"))
            if (tool_name == "url_fetch" and isinstance(arguments, dict)
                    and "search_step_id" in arguments):
                selected = "SearchResultReference"
            if selected is not None and branch != selected:
                continue
            location = location[:3] + location[4:]
        path = ".".join(
            str(part) if isinstance(part, int) or part in known_fields else "<field>"
            for part in location[:6]
        ) or "plan"
        diagnostics.append(f"{path}: {item['type']}")
        if len(diagnostics) == 5:
            break
    return "; ".join(diagnostics)[:500]


class Planner:
    """Ask the LLM for a proposal and return only a fully validated ``Plan``."""

    def __init__(
        self, client: LLMClient, registry: ToolRegistry,
        *, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._registry = registry
        self._sleep = sleep

    def propose(
        self,
        goal: Goal,
        context: Mapping[str, Any] | None = None,
        *,
        on_retry: Callable[[str], None] | None = None,
    ) -> Plan:
        schema = Plan.model_json_schema(by_alias=False)
        tool_metadata = self._tool_metadata()
        request_payload: dict[str, Any] = {
            "instruction": PLAN_REQUEST_TEMPLATE,
            "goal": goal.model_dump(mode="json"),
            "tool_registry": tool_metadata,
            "max_plan_steps": MAX_PLAN_STEPS,
            "schema": schema,
        }
        if context is not None:
            request_payload["context"] = self._bounded_json_value(context)

        for attempt in range(1, MAX_MODEL_ATTEMPTS + 1):
            try:
                response = self._client.generate(
                    "plan_proposal", request_payload, json.dumps(schema, sort_keys=True)
                )
            except GroqLLMError as error:
                rate_limited = error.category.startswith("http_429") or error.category == "rate_limited"
                delay = error.retry_after_seconds
                if delay is None:
                    delay = MAX_MODEL_RETRY_DELAY_SECONDS if rate_limited else 1.0
                if (error.retryable and attempt < MAX_MODEL_ATTEMPTS
                        and 0 <= delay <= MAX_MODEL_RETRY_DELAY_SECONDS):
                    if on_retry is not None:
                        on_retry(f"{error.category}; waiting {delay:g}s before model attempt {attempt + 1}/{MAX_MODEL_ATTEMPTS}")
                    self._sleep(delay)
                    continue
                raise PlannerProviderError(
                    attempts=attempt,
                    retryable=error.retryable,
                    category=error.category,
                    retry_after_seconds=error.retry_after_seconds,
                ) from None

            try:
                plan = Plan.model_validate_json(response.content)
                if plan.goal_id != goal.goal_id:
                    raise _PlanContractError("goal_id_mismatch")
                self._validate_registered_steps(plan, tool_metadata)
                for step in plan.steps:
                    if isinstance(step.input, URLFetchInput) and step.input.url not in goal.text:
                        raise _PlanContractError("fetch_requires_search_result_reference")
                    if (step.fallback is not None
                            and isinstance(step.fallback.arguments, URLFetchInput)
                            and step.fallback.arguments.url not in goal.text):
                        raise _PlanContractError("fallback_fetch_requires_goal_url")
                return plan
            except ValueError as error:
                feedback = _validation_feedback(error, schema, response.content)
                if attempt >= MAX_MODEL_ATTEMPTS:
                    raise PlannerOutputError(
                        attempts=attempt, reason=feedback
                    ) from None
                if on_retry is not None:
                    on_retry(f"malformed structured planner output ({feedback}); waiting {MAX_MODEL_RETRY_DELAY_SECONDS:g}s before model attempt {attempt + 1}/{MAX_MODEL_ATTEMPTS}")
                request_payload = self._repair_payload(
                    goal,
                    schema,
                    tool_metadata=tool_metadata,
                    invalid_response=response.content[:MAX_PLANNER_REPAIR_CHARS],
                    validation_errors=feedback,
                    context=context,
                )
                # A successful HTTP response already consumed quota. Pace its
                # repair as well as HTTP retries to avoid a second token burst.
                self._sleep(MAX_MODEL_RETRY_DELAY_SECONDS)

        raise AssertionError("bounded planner loop exited unexpectedly")

    @staticmethod
    def _repair_payload(
        goal: Goal,
        schema: dict[str, Any],
        *,
        tool_metadata: list[dict[str, Any]],
        invalid_response: str,
        validation_errors: str,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "instruction": PLANNER_REPAIR_TEMPLATE,
            "goal": goal.model_dump(mode="json"),
            "tool_registry": tool_metadata,
            "schema": schema,
            "invalid_response": invalid_response,
            "validation_errors": validation_errors,
            "max_plan_steps": MAX_PLAN_STEPS,
        }
        if context is not None:
            payload["context"] = Planner._bounded_json_value(context)
        return payload

    @staticmethod
    def _bounded_json_value(value: Mapping[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value, ensure_ascii=True, default=str)
        except (TypeError, ValueError):
            return {"omitted": "context was not JSON serializable"}
        if len(encoded) > MAX_PLANNER_REPAIR_CHARS:
            return {"omitted": "context exceeded the planning context limit"}
        return json.loads(encoded)

    def _tool_metadata(self) -> list[dict[str, Any]]:
        metadata = self._registry.metadata()
        if not metadata:
            raise ValueError("planner requires at least one registered tool")
        return [item.model_dump(mode="json") for item in metadata]

    @staticmethod
    def _validate_registered_steps(
        plan: Plan, tool_metadata: list[dict[str, Any]]
    ) -> None:
        registered_names = {item["name"] for item in tool_metadata}
        for step in plan.steps:
            if step.tool_name.value not in registered_names:
                raise _PlanContractError("unregistered_step_tool")
            if step.fallback is not None and step.fallback.tool_name.value not in registered_names:
                raise _PlanContractError("unregistered_fallback_tool")
