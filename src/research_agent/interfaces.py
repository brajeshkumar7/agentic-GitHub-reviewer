"""Protocol-only boundaries for components implemented in later phases."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel

from research_agent.models import (
    Evidence,
    Failure,
    FinalReport,
    Goal,
    LLMResponse,
    Plan,
    PlanStep,
    RecoveryAction,
    ToolCall,
    ToolResult,
    ValidatedPlan,
)
from research_agent.state import AgentState
from research_agent.tools.base import Tool
from research_agent.tools.base import ToolMetadata


class AgentController(Protocol):
    def run(self, goal_text: str) -> FinalReport: ...


class PlannerPort(Protocol):
    def propose(
        self,
        goal: Goal,
        context: Any = None,
        *,
        on_retry: Callable[[str], None] | None = None,
    ) -> Plan: ...


class PlanValidatorPort(Protocol):
    def validate(
        self, goal: Goal, proposal: Plan, state: AgentState, registry: ToolRegistry
    ) -> ValidatedPlan | Failure: ...


class ExecutionEngine(Protocol):
    def execute(self, plan: ValidatedPlan, state: AgentState) -> AgentState: ...


class ToolRegistry(Protocol):
    def get(self, name: str) -> Tool: ...

    def metadata(self) -> list[ToolMetadata]: ...

    def validate_arguments(
        self, name: str, arguments: BaseModel | dict[str, Any]
    ) -> BaseModel: ...

    def dispatch(self, call: ToolCall) -> ToolResult: ...


class WebSearchTool(Tool, Protocol):
    pass


class URLFetchTool(Tool, Protocol):
    pass


class CalculatorTool(Tool, Protocol):
    pass


class FailureHandler(Protocol):
    def recover(
        self, failure: Failure, state: AgentState, step: PlanStep
    ) -> RecoveryAction: ...


class EvidenceStore(Protocol):
    def add(self, evidence: Evidence) -> str: ...

    def get(self, evidence_id: str) -> Evidence: ...

    def for_goal(self, goal_id: str) -> list[Evidence]: ...


class EventLogger(Protocol):
    def emit(self, event: Any) -> None: ...


class ReportGenerator(Protocol):
    def generate(
        self, goal: Goal, plan: Plan, state: AgentState
    ) -> FinalReport: ...


class LLMClient(Protocol):
    def generate(
        self, operation: str, payload: dict[str, Any], expected_schema: str
    ) -> LLMResponse: ...

