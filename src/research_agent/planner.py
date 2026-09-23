"""Structured planner with strict local validation and one bounded repair."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from research_agent.interfaces import LLMClient, ToolRegistry
from research_agent.limits import (
    MAX_MODEL_ATTEMPTS,
    MAX_PLAN_STEPS,
    MAX_PLANNER_REPAIR_CHARS,
)
from research_agent.models import Goal, Plan
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

    def __init__(self, *, attempts: int, retryable: bool, category: str) -> None:
        self.attempts = attempts
        self.retryable = retryable
        self.category = category
        super().__init__(f"planner provider failure ({category}) after {attempts} attempt(s)")


class Planner:
    """Ask the LLM for a proposal and return only a fully validated ``Plan``."""

    def __init__(self, client: LLMClient, registry: ToolRegistry) -> None:
        self._client = client
        self._registry = registry

    def propose(
        self,
        goal: Goal,
        context: Mapping[str, Any] | None = None,
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
                if error.retryable and attempt < MAX_MODEL_ATTEMPTS:
                    continue
                raise PlannerProviderError(
                    attempts=attempt,
                    retryable=error.retryable,
                    category=error.category,
                ) from None

            try:
                plan = Plan.model_validate_json(response.content)
                if plan.goal_id != goal.goal_id:
                    raise ValueError("plan goal_id does not match the submitted goal")
                self._validate_registered_steps(plan, tool_metadata)
                return plan
            except (ValidationError, ValueError, json.JSONDecodeError):
                if attempt >= MAX_MODEL_ATTEMPTS:
                    raise PlannerOutputError(
                        attempts=attempt, reason="schema or plan invariant validation failed"
                    ) from None
                request_payload = self._repair_payload(
                    goal,
                    schema,
                    tool_metadata=tool_metadata,
                    invalid_response=response.content[:MAX_PLANNER_REPAIR_CHARS],
                    context=context,
                )

        raise AssertionError("bounded planner loop exited unexpectedly")

    @staticmethod
    def _repair_payload(
        goal: Goal,
        schema: dict[str, Any],
        *,
        tool_metadata: list[dict[str, Any]],
        invalid_response: str,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "instruction": PLANNER_REPAIR_TEMPLATE,
            "goal": goal.model_dump(mode="json"),
            "tool_registry": tool_metadata,
            "schema": schema,
            "invalid_response": invalid_response,
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
                raise ValueError("plan references a tool absent from the registry")
            if step.fallback is not None and step.fallback.tool_name.value not in registered_names:
                raise ValueError("fallback references a tool absent from the registry")
