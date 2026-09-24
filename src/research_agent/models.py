"""Strict, transport-agnostic models for the architecture contract.

These models validate data only. They do not call services or execute plans.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, TypeAlias
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import (
    AliasChoices,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)

from research_agent.limits import (
    CALCULATOR_MAX_EXPRESSION_CHARS,
    MAX_PLAN_STEPS,
    MAX_SEARCH_QUERY_CHARS,
    MAX_SEARCH_QUERY_WORDS,
    MAX_SEARCH_RESULTS,
    MAX_TOOL_ATTEMPTS,
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


class ReportStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


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
    GOAL_RECEIVED = "GOAL_RECEIVED"
    STATE_TRANSITION = "STATE_TRANSITION"
    RUN_STARTED = "RUN_STARTED"
    PLAN_CREATED = "PLAN_CREATED"
    PLAN_REJECTED = "PLAN_REJECTED"
    PLAN_VALIDATED = "PLAN_VALIDATED"
    STEP_STARTED = "STEP_STARTED"
    TOOL_CALL_STARTED = "TOOL_CALL_STARTED"
    TOOL_CALL_SUCCEEDED = "TOOL_CALL_SUCCEEDED"
    TOOL_CALL_FAILED = "TOOL_CALL_FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    RETRY_ATTEMPTED = "RETRY_ATTEMPTED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_APPLIED = "RECOVERY_APPLIED"
    REPLAN_STARTED = "REPLAN_STARTED"
    FAILURE_INJECTED = "FAILURE_INJECTED"
    EVIDENCE_RECORDED = "EVIDENCE_RECORDED"
    STEP_COMPLETED = "STEP_COMPLETED"
    STEP_FAILED = "STEP_FAILED"
    STEP_SKIPPED = "STEP_SKIPPED"
    SYNTHESIS_STARTED = "SYNTHESIS_STARTED"
    FINAL_REPORT_CREATED = "FINAL_REPORT_CREATED"
    REPORT_VALIDATED = "REPORT_VALIDATED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    RUN_COMPLETED = "RUN_COMPLETED"


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


class FailureInjectionMode(str, Enum):
    TOOL_TIMEOUT = "tool_timeout"
    MALFORMED_TOOL_RESPONSE = "malformed_tool_response"


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
    query: Annotated[
        StrictStr,
        Field(min_length=1, max_length=MAX_SEARCH_QUERY_CHARS),
    ]
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    max_results: Annotated[int, Field(gt=0, le=MAX_SEARCH_RESULTS)]

    @field_validator("query")
    @classmethod
    def non_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("search query must not be blank")
        if len(value.split()) > MAX_SEARCH_QUERY_WORDS:
            raise ValueError("search query exceeds the word limit")
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
    title: Annotated[StrictStr, Field(min_length=1, max_length=500)]
    url: Annotated[StrictStr, Field(max_length=2_048)]
    snippet: Annotated[StrictStr, Field(max_length=2_000)]
    source: Annotated[StrictStr, Field(min_length=1, max_length=255)]
    published_at: AwareDatetime | None = None

    @field_validator("url")
    @classmethod
    def valid_web_url(cls, value: str) -> str:
        return _validate_web_url(value, require_https=False)


class SearchResults(StrictModel):
    results: list[SearchResult] = Field(default_factory=list)
    provider_metadata: dict[StrictStr, StrictStr] = Field(default_factory=dict)


class URLFetchInput(StrictModel):
    url: Annotated[StrictStr, Field(max_length=2_048)]

    @field_validator("url")
    @classmethod
    def https_only(cls, value: str) -> str:
        return _validate_web_url(value, require_https=True)


class FetchedPage(StrictModel):
    final_url: Annotated[StrictStr, Field(max_length=2_048)]
    status: Annotated[int, Field(ge=200, lt=300)]
    title: Annotated[StrictStr, Field(max_length=1_000)]
    publisher: StrictStr | None = None
    published_at: AwareDatetime | None = None
    extracted_text: Annotated[StrictStr, Field(max_length=20_000)]
    retrieved_at: AwareDatetime
    truncated: bool

    @field_validator("final_url")
    @classmethod
    def valid_final_url(cls, value: str) -> str:
        return _validate_web_url(value, require_https=True)


class CalculatorInput(StrictModel):
    expression: Annotated[
        StrictStr, Field(min_length=1, max_length=CALCULATOR_MAX_EXPRESSION_CHARS)
    ] | None = None
    operation: CalculatorOperation | None = None
    operands: Annotated[list[Decimal], Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def validate_operands(self) -> CalculatorInput:
        if self.expression is not None:
            if not self.expression.strip():
                raise ValueError("calculator expression must not be blank")
            if self.operation is not None or self.operands is not None:
                raise ValueError("provide expression or operation and operands, not both")
            return self
        if self.operation is None or self.operands is None:
            raise ValueError("calculator requires an expression or operation and operands")
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
    expression: StrictStr | None = None
    operation: CalculatorOperation | None = None
    operands: list[Decimal] = Field(default_factory=list)
    result: Decimal

    @model_validator(mode="after")
    def validate_calculation_shape(self) -> Calculation:
        if self.expression is not None:
            if self.operation is not None or self.operands:
                raise ValueError("expression result cannot also contain operation operands")
        elif self.operation is None or not self.operands:
            raise ValueError("calculation requires an expression or operation operands")
        return self

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


class SearchResultReference(StrictModel):
    """Plan-only binding to one result from a direct search dependency."""

    search_step_id: Annotated[StrictStr, Field(min_length=1)]
    result_index: Annotated[int, Field(ge=0, lt=MAX_SEARCH_RESULTS)]


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
    id: Annotated[
        StrictStr,
        Field(
            min_length=1,
            validation_alias=AliasChoices("id", "step_id"),
            serialization_alias="step_id",
        ),
    ]
    objective: Annotated[
        StrictStr,
        Field(
            min_length=1,
            validation_alias=AliasChoices("objective", "description"),
            serialization_alias="description",
        ),
    ]
    tool_name: ToolName
    input: ToolArguments | SearchResultReference = Field(
        validation_alias=AliasChoices("input", "arguments"),
        serialization_alias="arguments",
    )
    expected_output: Annotated[
        StrictStr,
        Field(
            min_length=1,
            validation_alias=AliasChoices("expected_output", "success_criteria"),
            serialization_alias="success_criteria",
        ),
    ]
    dependencies: list[StrictStr] = Field(
        validation_alias=AliasChoices("dependencies", "depends_on"),
        serialization_alias="depends_on",
    )
    status: StepStatus
    fallback: ToolCallTemplate | None = None
    recovery_of_step_id: StrictStr | None = None

    @model_validator(mode="after")
    def validate_step(self) -> PlanStep:
        if isinstance(self.input, SearchResultReference):
            if self.tool_name != ToolName.URL_FETCH:
                raise ValueError("search references are permitted only for URL fetch")
            if self.input.search_step_id not in self.dependencies:
                raise ValueError("search reference requires a direct dependency")
        else:
            _validate_tool_arguments(self.tool_name, self.input)
        if self.status != StepStatus.PENDING:
            raise ValueError("new plan steps must have PENDING status")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("step dependencies must be unique")
        if self.id in self.dependencies:
            raise ValueError("a step cannot depend on itself")
        return self

    @property
    def step_id(self) -> str:
        return self.id

    @property
    def description(self) -> str:
        return self.objective

    @property
    def arguments(self) -> ToolArguments | SearchResultReference:
        return self.input

    @property
    def success_criteria(self) -> str:
        return self.expected_output

    @property
    def depends_on(self) -> list[str]:
        return self.dependencies


class Plan(StrictModel):
    plan_id: UUID = Field(default_factory=uuid4)
    goal_id: UUID
    revision: Annotated[int, Field(ge=1)] = 1
    steps: Annotated[
        list[PlanStep], Field(min_length=1, max_length=MAX_PLAN_STEPS)
    ]
    replaces_plan_id: UUID | None = None

    @model_validator(mode="after")
    def validate_steps_and_dependencies(self) -> Plan:
        step_ids = [step.id for step in self.steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("plan step IDs must be unique")
        known_ids = set(step_ids)
        by_id = {step.id: step for step in self.steps}
        dependencies: dict[str, list[str]] = {}
        for step in self.steps:
            if isinstance(step.input, SearchResultReference):
                source = by_id.get(step.input.search_step_id)
                if source is None or source.tool_name != ToolName.WEB_SEARCH:
                    raise ValueError("fetch reference must identify a search step")
            missing = set(step.dependencies) - known_ids
            if missing:
                raise ValueError(f"unknown dependencies for {step.id}: {sorted(missing)}")
            dependencies[step.id] = step.dependencies

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
    validator_version: StrictStr = "phase3"


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
    attempt: Annotated[int, Field(ge=1, le=MAX_TOOL_ATTEMPTS)]
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


class LLMResponse(StrictModel):
    content: StrictStr
    provider: StrictStr
    request_id: StrictStr | None = None


class Evidence(StrictModel):
    evidence_id: UUID = Field(default_factory=uuid4)
    goal_id: UUID
    step_id: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    source_url: Annotated[StrictStr, Field(min_length=1, max_length=2_048)]
    title: Annotated[StrictStr, Field(min_length=1, max_length=500)]
    publisher: StrictStr | None = None
    source_type: SourceType
    source_group_id: StrictStr
    published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime
    supporting_text: Annotated[StrictStr, Field(min_length=1, max_length=20_000)]
    supports: list[Annotated[StrictStr, Field(min_length=1, max_length=300)]] = Field(
        default_factory=list
    )
    verification: EvidenceVerification = EvidenceVerification.CANDIDATE

    @field_validator("step_id", "title", "supporting_text")
    @classmethod
    def evidence_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence provenance and text fields must not be blank")
        return value

    @field_validator("source_url")
    @classmethod
    def source_must_be_https(cls, value: str) -> str:
        return _validate_web_url(value, require_https=True)


class ExecutionEvent(StrictModel):
    event_id: UUID = Field(default_factory=uuid4)
    execution_id: UUID
    # `run_id` is retained as a compatibility field for existing failure/report references.
    run_id: UUID
    sequence: Annotated[int, Field(ge=1)]
    timestamp: AwareDatetime
    event_type: EventType
    state: RunState
    step_id: StrictStr | None = None
    call_id: UUID | None = None
    tool_name: ToolName | None = None
    attempt: Annotated[int, Field(ge=1, le=MAX_TOOL_ATTEMPTS)] | None = None
    status: EventOutcome
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def event_time_is_utc(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def execution_and_run_ids_match(self) -> ExecutionEvent:
        if self.execution_id != self.run_id:
            raise ValueError("execution_id must match run_id")
        return self

    @property
    def outcome(self) -> EventOutcome:
        """Compatibility accessor; serialized event contract calls this `status`."""
        return self.status

    @property
    def summary(self) -> str:
        """Return the concise, public-safe summary stored in event metadata."""
        value = self.metadata.get("summary")
        return value if isinstance(value, str) else self.event_type.value


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
    attempt: Annotated[int, Field(ge=1, le=MAX_TOOL_ATTEMPTS)]
    outcome: EventOutcome
    duration_ms: Annotated[int, Field(ge=0)] | None = None


class ExecutionSummary(StrictModel):
    events: list[ExecutionEvent] = Field(default_factory=list)
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    retry_counts: dict[StrictStr, Annotated[int, Field(ge=0)]] = Field(
        default_factory=dict
    )
    recovered_failures: list[RecoveryAction] = Field(default_factory=list)


class ReportPlanStep(StrictModel):
    id: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    objective: Annotated[StrictStr, Field(min_length=1, max_length=1_000)]
    tool_name: ToolName
    status: StepStatus
    dependencies: list[Annotated[StrictStr, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list
    )


class ReportExecutionSummary(StrictModel):
    steps_total: Annotated[int, Field(ge=0)]
    steps_completed: Annotated[int, Field(ge=0)]
    steps_failed: Annotated[int, Field(ge=0)]
    retries: Annotated[int, Field(ge=0)]


class Finding(StrictModel):
    finding_id: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    title: Annotated[StrictStr, Field(min_length=1, max_length=500)]
    summary: Annotated[StrictStr, Field(min_length=1, max_length=4_000)]
    evidence_ids: Annotated[list[UUID], Field(min_length=1, max_length=20)]

    @field_validator("title", "summary")
    @classmethod
    def generated_content_must_not_add_sources(cls, value: str) -> str:
        if re.search(r"(?:https?://|www\.)", value, flags=re.IGNORECASE):
            raise ValueError("findings must reference evidence IDs, not introduce source URLs")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def evidence_references_must_be_unique(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("finding evidence IDs must be unique")
        return value


class FinalReport(StrictModel):
    status: ReportStatus
    goal: Annotated[StrictStr, Field(min_length=1)]
    plan: list[ReportPlanStep] = Field(default_factory=list)
    execution_summary: ReportExecutionSummary
    failures: list[Failure] = Field(default_factory=list)
    recoveries: list[RecoveryAction] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    limitations: list[StrictStr] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report(self) -> FinalReport:
        source_ids = [source.evidence_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source evidence IDs must be unique")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        if set(source_ids) != set(evidence_ids):
            raise ValueError("sources must be an exact projection of collected evidence")
        for source in self.sources:
            evidence = evidence_by_id[source.evidence_id]
            if (
                source.url != evidence.source_url
                or source.title != evidence.title
                or source.publisher != evidence.publisher
                or source.source_type != evidence.source_type
                or source.published_at != evidence.published_at
                or source.retrieved_at != evidence.retrieved_at
                or source.supports != evidence.supports
            ):
                raise ValueError("source metadata does not match collected evidence")
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding IDs must be unique")
        for finding in self.findings:
            missing = set(finding.evidence_ids) - set(evidence_ids)
            if missing:
                raise ValueError(
                    f"unknown evidence IDs for {finding.finding_id}: {sorted(missing)}"
                )
            if any(
                evidence_by_id[evidence_id].verification != EvidenceVerification.VERIFIED
                for evidence_id in finding.evidence_ids
            ):
                raise ValueError("findings may cite only verified evidence")
        if self.status == ReportStatus.COMPLETED and (
            not self.findings
            or not any(
                item.verification == EvidenceVerification.VERIFIED
                for item in self.evidence
            )
        ):
            raise ValueError("completed report requires findings grounded in verified evidence")
        plan_ids = {step.id for step in self.plan}
        summary = self.execution_summary
        if summary.steps_total != len(self.plan):
            raise ValueError("execution summary total must match the plan")
        if summary.steps_completed != sum(step.status == StepStatus.SUCCEEDED for step in self.plan):
            raise ValueError("execution summary completed count must match plan statuses")
        if summary.steps_failed != sum(step.status == StepStatus.FAILED for step in self.plan):
            raise ValueError("execution summary failed count must match plan statuses")
        for step in self.plan:
            if set(step.dependencies) - plan_ids:
                raise ValueError("report plan contains a missing dependency")
        known_failures = {failure.failure_id for failure in self.failures}
        if any(action.failure_id not in known_failures for action in self.recoveries):
            raise ValueError("recovery references a failure absent from the report")
        return self

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize the validated report to machine-readable JSON."""
        return self.model_dump_json(indent=indent)

    def to_markdown(self) -> str:
        """Render a human-readable report while keeping observations distinct from synthesis."""
        return _render_report_markdown(self)


def _safe_markdown(value: str) -> str:
    """Escape untrusted text before placing it in the Markdown document."""
    escaped = html.escape(value.replace("\r", " ").replace("\n", " "), quote=True)
    for char in ("\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "+", "-", ".", "!", "|"):
        escaped = escaped.replace(char, f"\\{char}")
    return escaped


def _safe_code(value: str) -> str:
    """Escape HTML and remove code-span delimiters for plain inline values."""
    return html.escape(value.replace("\r", " ").replace("\n", " "), quote=True).replace("`", "")


def _render_report_markdown(report: FinalReport) -> str:
    lines = [
        "# Research Brief",
        "",
        "## Goal",
        "",
        _safe_markdown(report.goal),
        "",
        f"**Status:** {report.status.value}",
        "",
        "## Plan",
        "",
    ]
    if report.plan:
        for step in report.plan:
            dependencies = ", ".join(_safe_markdown(item) for item in step.dependencies) or "none"
            lines.append(
                f"- **{_safe_markdown(step.id)}** — {_safe_markdown(step.objective)} "
                f"({step.tool_name.value}; {step.status.value}; dependencies: {dependencies})"
            )
    else:
        lines.append("No plan was available.")

    summary = report.execution_summary
    lines.extend(
        [
            "",
            "## Execution Summary",
            "",
            f"- Steps total: {summary.steps_total}",
            f"- Steps completed: {summary.steps_completed}",
            f"- Steps failed: {summary.steps_failed}",
            f"- Retries: {summary.retries}",
            "",
            "## Findings",
            "",
            "Generated synthesis grounded only in the verified evidence listed below.",
            "",
        ]
    )
    if report.findings:
        for finding in report.findings:
            citations = ", ".join(str(item) for item in finding.evidence_ids)
            lines.extend(
                [
                    f"### {_safe_markdown(finding.title)}",
                    "",
                    _safe_markdown(finding.summary),
                    "",
                    f"Evidence IDs: {citations}",
                    "",
                ]
            )
    else:
        lines.extend(["No findings could be synthesized from verified evidence.", ""])

    lines.extend(["## Evidence", "", "Observed information collected from tool results:", ""])
    if report.evidence:
        for item in report.evidence:
            lines.extend(
                [
                    f"- **{_safe_markdown(item.title)}** ({item.verification.value})",
                    f"  - URL: `{_safe_code(item.source_url)}`",
                    f"  - Producing step: `{_safe_code(item.step_id)}`",
                    f"  - Retrieved: {item.retrieved_at.isoformat()}",
                    f"  - Extract: {_safe_markdown(item.supporting_text)}",
                ]
            )
    else:
        lines.append("No evidence was collected.")

    lines.extend(["", "## Failures and Recovery", ""])
    if report.failures:
        for failure in report.failures:
            lines.append(
                f"- **{failure.category.value}** (step {failure.step_id or 'run'}): "
                f"{_safe_markdown(failure.message)}"
            )
    else:
        lines.append("No failures recorded.")
    if report.recoveries:
        lines.extend(["", "Recovery actions:"])
        for action in report.recoveries:
            detail = (
                f"; replacement tool {action.replacement_call.tool_name.value}"
                if action.replacement_call is not None
                else ""
            )
            lines.append(
                f"- {action.kind.value} for step {action.target_step_id or 'run'} "
                f"({action.reason_code.value}){detail}"
            )
    else:
        lines.extend(["", "No recovery actions recorded."])

    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {_safe_markdown(item)}" for item in report.limitations)
    if not report.limitations:
        lines.append("No additional limitations recorded.")

    lines.extend(["", "## Sources", ""])
    if report.sources:
        for source in report.sources:
            publisher = f" — {_safe_markdown(source.publisher)}" if source.publisher else ""
            lines.append(
                f"- {_safe_markdown(source.title)}{publisher}; "
                f"URL: `{_safe_code(source.url)}`; retrieved {source.retrieved_at.isoformat()}"
            )
    else:
        lines.append("No sources were collected.")
    return "\n".join(lines).rstrip() + "\n"


LLMOperationName: TypeAlias = Annotated[
    StrictStr,
    Field(pattern=r"^(plan_proposal|plan_revision|research_summary)$"),
]


def utc_now() -> datetime:
    """Return an aware UTC timestamp for CLI and test scaffolding."""

    return datetime.now(timezone.utc)
