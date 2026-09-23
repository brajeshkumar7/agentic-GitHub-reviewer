"""Strict, transport-agnostic models for the architecture contract.

These models validate data only. They do not call services or execute plans.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, TypeAlias
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    """Base for boundary models: no coercion or undeclared fields."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
    )


class ToolName(str, Enum):
    WEB_SEARCH = "web_search"
    URL_FETCH = "url_fetch"
    CALCULATOR = "calculator"


class RunState(str, Enum):
    RECEIVED = "RECEIVED"
    PLANNING = "PLANNING"
    PLAN_VALIDATION = "PLAN_VALIDATION"
    EXECUTING = "EXECUTING"
    RECOVERY = "RECOVERY"
    SYNTHESIZING = "SYNTHESIZING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ToolCallKind(str, Enum):
    PRIMARY = "primary"
    RETRY = "retry"
    FALLBACK = "fallback"


class ToolResultStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CalculatorOperation(str, Enum):
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    MEAN = "mean"
    PERCENTAGE = "percentage"


class SourceType(str, Enum):
    PRIMARY = "primary"
    INDEPENDENT_SECONDARY = "independent_secondary"
    OTHER = "other"


class EvidenceVerification(str, Enum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    CONTRADICTORY = "contradictory"


class EventType(str, Enum):
    RUN_STARTED = "run_started"
    PLAN_CREATED = "plan_created"
    PLAN_REJECTED = "plan_rejected"
    PLAN_VALIDATED = "plan_validated"
    STEP_STARTED = "step_started"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_SUCCEEDED = "tool_call_succeeded"
    TOOL_CALL_FAILED = "tool_call_failed"
    RETRY_SCHEDULED = "retry_scheduled"
    RECOVERY_APPLIED = "recovery_applied"
    EVIDENCE_RECORDED = "evidence_recorded"
    STEP_COMPLETED = "step_completed"
    STEP_SKIPPED = "step_skipped"
    REPORT_VALIDATED = "report_validated"
    RUN_COMPLETED = "run_completed"


class EventOutcome(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    SCHEDULED = "scheduled"
    SKIPPED = "skipped"
    RECOVERED = "recovered"
    COMPLETED = "completed"


class FailureCategory(str, Enum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    INVALID_RESPONSE = "invalid_response"
    INVALID_ARGUMENT = "invalid_argument"
    NOT_FOUND = "not_found"
    AUTH_CONFIG = "auth_config"
    UNSAFE_URL = "unsafe_url"
    EMPTY_RESULTS = "empty_results"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CALCULATOR_ERROR = "calculator_error"
    STATE_INVARIANT = "state_invariant"
    SYNTHESIS_INVALID = "synthesis_invalid"
    RETRY_EXHAUSTED = "retry_exhausted"
    LLM_ERROR = "llm_error"


class FailureOrigin(str, Enum):
    PLANNER = "planner"
    VALIDATOR = "validator"
    LLM = "llm"
    TOOL = "tool"
    EXECUTOR = "executor"
    EVIDENCE = "evidence"
    REPORT = "report"


class Retryability(str, Enum):
    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"
    SEMANTIC = "semantic"


class RecoveryKind(str, Enum):
    RETRY = "retry"
    FALLBACK = "fallback"
    REPLAN = "replan"
    MARK_FAILED = "mark_failed"
    SKIP_DEPENDENT = "skip_dependent"
    CONTINUE_PARTIAL = "continue_partial"


class RecoveryReason(str, Enum):
    TRANSIENT = "transient"
    EMPTY_RESULTS = "empty_results"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INVALID_OUTPUT = "invalid_output"
    PERMANENT_ERROR = "permanent_error"
    BUDGET_EXHAUSTED = "budget_exhausted"


class DevelopmentConfidence(float, Enum):
    LOW = 0.25
    MEDIUM = 0.5
    HIGH = 0.75
    VERY_HIGH = 1.0


class DateWindow(StrictModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def validate_order(self) -> DateWindow:
        if self.start > self.end:
            raise ValueError("date-window start must not be after end")
        return self


class Goal(StrictModel):
    goal_id: UUID = Field(default_factory=uuid4)
    text: Annotated[StrictStr, Field(min_length=1)]
    requested_window: DateWindow | None = None
    run_started_at: AwareDatetime

    @field_validator("text")
    @classmethod
    def non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("goal text must not be blank")
        return value.strip()


class WebSearchInput(StrictModel):
    query: Annotated[StrictStr, Field(min_length=1)]
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    max_results: Annotated[int, Field(gt=0)]

    @field_validator("query")
    @classmethod
    def non_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("search query must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def validate_dates(self) -> WebSearchInput:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("search start must not be after end")
        return self


def _validate_web_url(value: str, *, require_https: bool) -> str:
    parts = urlsplit(value)
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    if parts.scheme.lower() not in allowed_schemes or not parts.hostname:
        expected = "HTTPS" if require_https else "HTTP or HTTPS"
        raise ValueError(f"URL must be an absolute {expected} URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL must not contain credentials")
    return value


class SearchResult(StrictModel):
    title: StrictStr
    url: StrictStr
    snippet: StrictStr
    published_at: AwareDatetime | None = None

    @field_validator("url")
    @classmethod
    def valid_web_url(cls, value: str) -> str:
        return _validate_web_url(value, require_https=False)


class SearchResults(StrictModel):
    results: list[SearchResult] = Field(default_factory=list)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class URLFetchInput(StrictModel):
    url: StrictStr

    @field_validator("url")
    @classmethod
    def https_only(cls, value: str) -> str:
        return _validate_web_url(value, require_https=True)


class FetchedPage(StrictModel):
    final_url: StrictStr
    title: StrictStr
    publisher: StrictStr | None = None
    published_at: AwareDatetime | None = None
    extracted_text: StrictStr
    retrieved_at: AwareDatetime
    truncated: bool

    @field_validator("final_url")
    @classmethod
    def valid_final_url(cls, value: str) -> str:
        return _validate_web_url(value, require_https=True)


class CalculatorInput(StrictModel):
    operation: CalculatorOperation
    operands: Annotated[list[Decimal], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_operands(self) -> CalculatorInput:
        if any(not value.is_finite() for value in self.operands):
            raise ValueError("calculator operands must be finite")
        exact_two = {
            CalculatorOperation.ADD,
            CalculatorOperation.SUBTRACT,
            CalculatorOperation.MULTIPLY,
            CalculatorOperation.DIVIDE,
            CalculatorOperation.PERCENTAGE,
        }
        if self.operation in exact_two and len(self.operands) != 2:
            raise ValueError(f"{self.operation.value} requires exactly two operands")
        if self.operation == CalculatorOperation.DIVIDE and self.operands[1] == 0:
            raise ValueError("division by zero is not allowed")
        if self.operation == CalculatorOperation.PERCENTAGE and self.operands[1] == 0:
            raise ValueError("percentage whole operand must not be zero")
        return self


class Calculation(StrictModel):
    operation: CalculatorOperation
    operands: list[Decimal]
    result: Decimal

    @field_validator("operands", mode="after")
    @classmethod
    def finite_operands(cls, values: list[Decimal]) -> list[Decimal]:
        if any(not value.is_finite() for value in values):
            raise ValueError("calculation operands must be finite")
        return values

    @field_validator("result")
    @classmethod
    def finite_result(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("calculation result must be finite")
        return value


ToolArguments: TypeAlias = WebSearchInput | URLFetchInput | CalculatorInput


def _validate_tool_arguments(tool_name: ToolName, arguments: ToolArguments) -> None:
    expected: dict[ToolName, type[StrictModel]] = {
        ToolName.WEB_SEARCH: WebSearchInput,
        ToolName.URL_FETCH: URLFetchInput,
        ToolName.CALCULATOR: CalculatorInput,
    }
    if not isinstance(arguments, expected[tool_name]):
        raise ValueError(f"arguments do not match tool {tool_name.value}")


class ToolCallTemplate(StrictModel):
    tool_name: ToolName
    arguments: ToolArguments

    @model_validator(mode="after")
    def arguments_match_tool(self) -> ToolCallTemplate:
        _validate_tool_arguments(self.tool_name, self.arguments)
        return self


class PlanStep(StrictModel):
    step_id: Annotated[StrictStr, Field(min_length=1)]
    description: Annotated[StrictStr, Field(min_length=1)]
    tool_name: ToolName
    arguments: ToolArguments
    depends_on: list[StrictStr] = Field(default_factory=list)
    success_criteria: Annotated[StrictStr, Field(min_length=1)]
    fallback: ToolCallTemplate | None = None
    recovery_of_step_id: StrictStr | None = None

    @model_validator(mode="after")
    def validate_step(self) -> PlanStep:
        _validate_tool_arguments(self.tool_name, self.arguments)
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("step dependencies must be unique")
        if self.step_id in self.depends_on:
            raise ValueError("a step cannot depend on itself")
        return self


class Plan(StrictModel):
    plan_id: UUID = Field(default_factory=uuid4)
    goal_id: UUID
    revision: Annotated[int, Field(ge=1)] = 1
    steps: Annotated[list[PlanStep], Field(min_length=1, max_length=8)]
    replaces_plan_id: UUID | None = None

    @model_validator(mode="after")
    def validate_steps_and_dependencies(self) -> Plan:
        step_ids = [step.step_id for step in self.steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("plan step IDs must be unique")
        known_ids = set(step_ids)
        dependencies: dict[str, list[str]] = {}
        for step in self.steps:
            missing = set(step.depends_on) - known_ids
            if missing:
                raise ValueError(f"unknown dependencies for {step.step_id}: {sorted(missing)}")
            dependencies[step.step_id] = step.depends_on

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("plan dependencies must be acyclic")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in step_ids:
            visit(step_id)
        return self


PlanProposal: TypeAlias = Plan


class ValidatedPlan(StrictModel):
    plan: Plan
    approved_at: AwareDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    validator_version: StrictStr = "phase2-placeholder"


class Failure(StrictModel):
    failure_id: UUID = Field(default_factory=uuid4)
    category: FailureCategory
    origin: FailureOrigin
    retryability: Retryability
    run_id: UUID
    step_id: StrictStr | None = None
    call_id: UUID | None = None
    message: Annotated[StrictStr, Field(min_length=1)]
    occurred_at: AwareDatetime


class ToolCall(StrictModel):
    call_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    step_id: StrictStr
    tool_name: ToolName
    arguments: ToolArguments
    attempt: Annotated[int, Field(ge=1, le=2)]
    kind: ToolCallKind
    created_at: AwareDatetime

    @model_validator(mode="after")
    def arguments_match_tool(self) -> ToolCall:
        _validate_tool_arguments(self.tool_name, self.arguments)
        return self


ToolOutput: TypeAlias = SearchResults | FetchedPage | Calculation


class ToolResult(StrictModel):
    call_id: UUID
    status: ToolResultStatus
    output: ToolOutput | None = None
    failure: Failure | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime

    @model_validator(mode="after")
    def validate_result_shape(self) -> ToolResult:
        if self.started_at > self.finished_at:
            raise ValueError("tool result finish time must not precede start time")
        if self.status == ToolResultStatus.SUCCEEDED:
            if self.output is None or self.failure is not None:
                raise ValueError("successful result requires output and no failure")
        elif self.output is not None or self.failure is None:
            raise ValueError("failed result requires failure and no output")
        return self


class Evidence(StrictModel):
    evidence_id: UUID = Field(default_factory=uuid4)
    source_url: StrictStr
    title: StrictStr
    publisher: StrictStr | None = None
    source_type: SourceType
    source_group_id: StrictStr
    published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime
    supporting_text: StrictStr
    supports: list[StrictStr] = Field(default_factory=list)
    verification: EvidenceVerification = EvidenceVerification.CANDIDATE

    @field_validator("source_url")
    @classmethod
    def source_must_be_https(cls, value: str) -> str:
        return _validate_web_url(value, require_https=True)


class ExecutionEvent(StrictModel):
    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    sequence: Annotated[int, Field(ge=1)]
    timestamp: AwareDatetime
    event_type: EventType
    state: RunState
    step_id: StrictStr | None = None
    call_id: UUID | None = None
    tool_name: ToolName | None = None
    attempt: Annotated[int, Field(ge=1, le=2)] | None = None
    outcome: EventOutcome
    summary: Annotated[StrictStr, Field(min_length=1)]


class RecoveryAction(StrictModel):
    action_id: UUID = Field(default_factory=uuid4)
    failure_id: UUID
    kind: RecoveryKind
    target_step_id: StrictStr | None = None
    replacement_call: ToolCall | None = None
    reason_code: RecoveryReason
    selected_at: AwareDatetime


class Development(StrictModel):
    development_id: StrictStr
    rank: Annotated[int, Field(ge=1, le=3)]
    title: StrictStr
    published_at: AwareDatetime | None = None
    description: StrictStr
    relevance: StrictStr
    comparison_note: StrictStr
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    evidence_ids: list[UUID] = Field(default_factory=list)


class ResearchBrief(StrictModel):
    topic: StrictStr
    time_window_start: AwareDatetime
    time_window_end: AwareDatetime
    summary: StrictStr
    developments: Annotated[list[Development], Field(max_length=3)] = Field(
        default_factory=list
    )
    comparison: StrictStr
    conclusion: StrictStr

    @model_validator(mode="after")
    def validate_window_and_ranks(self) -> ResearchBrief:
        if self.time_window_start > self.time_window_end:
            raise ValueError("research window start must not be after end")
        ranks = [development.rank for development in self.developments]
        if len(set(ranks)) != len(ranks):
            raise ValueError("development ranks must be unique")
        return self


class SourceCitation(StrictModel):
    evidence_id: UUID
    url: StrictStr
    title: StrictStr
    publisher: StrictStr | None = None
    source_type: SourceType
    published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime
    supports: list[StrictStr] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def source_must_be_https(cls, value: str) -> str:
        return _validate_web_url(value, require_https=True)


class ToolCallSummary(StrictModel):
    call_id: UUID
    step_id: StrictStr
    tool_name: ToolName
    attempt: Annotated[int, Field(ge=1, le=2)]
    outcome: EventOutcome
    duration_ms: Annotated[int, Field(ge=0)] | None = None


class ExecutionSummary(StrictModel):
    events: list[ExecutionEvent] = Field(default_factory=list)
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    retry_counts: dict[StrictStr, Annotated[int, Field(ge=0)]] = Field(
        default_factory=dict
    )
    recovered_failures: list[RecoveryAction] = Field(default_factory=list)


class FinalReport(StrictModel):
    schema_version: StrictStr = "1.0"
    run_id: UUID
    status: RunState
    goal: Annotated[StrictStr, Field(min_length=1)]
    run_started_at: AwareDatetime
    run_finished_at: AwareDatetime
    research_brief: ResearchBrief
    sources: list[SourceCitation] = Field(default_factory=list)
    plan: Plan
    execution: ExecutionSummary = Field(default_factory=ExecutionSummary)
    failures: list[Failure] = Field(default_factory=list)
    limitations: list[StrictStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report(self) -> FinalReport:
        terminal_states = {RunState.COMPLETED, RunState.PARTIAL, RunState.FAILED}
        if self.status not in terminal_states:
            raise ValueError("final report status must be terminal")
        if self.run_started_at > self.run_finished_at:
            raise ValueError("report finish time must not precede start time")
        source_ids = [source.evidence_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source evidence IDs must be unique")
        known_ids = set(source_ids)
        for development in self.research_brief.developments:
            missing = set(development.evidence_ids) - known_ids
            if missing:
                raise ValueError(
                    f"unknown evidence IDs for {development.development_id}: {sorted(missing)}"
                )
        return self


LLMOperationName: TypeAlias = Annotated[
    StrictStr,
    Field(pattern=r"^(plan_proposal|plan_revision|research_summary)$"),
]


def utc_now() -> datetime:
    """Return an aware UTC timestamp for CLI and test scaffolding."""

    return datetime.now(timezone.utc)
