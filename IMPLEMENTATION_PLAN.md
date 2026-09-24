# Sequential Implementation Plan

Implement one phase at a time. Do not start a later phase until the current phase's tests and acceptance criteria pass and `PROGRESS.md` records the evidence.

## Phase 0 — Project control documents

**Objective:** establish the assignment scope, safety rules, and initial requirements.

**Files/components affected:** `AGENTS.md`, `PROJECT_SPEC.md`, `IMPLEMENTATION_PLAN.md`, `PROGRESS.md`, `DECISIONS.md`, `FAILURE_MODES.md`, `EVALUATION.md`, `SECURITY.md`.

**Implementation work:** document the agent goal, deliverables, controls, assumptions, and phased workflow.

**Tests:** manual document inventory and cross-reference review; no executable tests for this documentation-only phase.

**Acceptance criteria:** all required control documents exist, are readable, and describe one consistent project direction.

**DO NOT IMPLEMENT YET:** any application package, API client, tool, planner, execution engine, or report behavior.

## Phase 1 — Technical architecture contract

**Objective:** specify the component boundaries, schemas, lifecycle, trace, and deterministic recovery policy.

**Files/components affected:** `ARCHITECTURE.md`, `DECISIONS.md`, with progress recorded in `PROGRESS.md`.

**Implementation work:** define the fourteen components and interfaces; Mermaid component and sequence diagrams; Pydantic schema strategy; lifecycle and terminal states; model/application/tool boundaries; bounded recovery rules.

**Tests:** manual review that every component/schema/transition is specified and aligned with `PROJECT_SPEC.md`, `FAILURE_MODES.md`, and `SECURITY.md`.

**Acceptance criteria:** architecture contract is reviewed and accepted; hidden reasoning stays out of the visible trace; no application behavior is implemented.

**DO NOT IMPLEMENT YET:** Python modules, dependencies, live LLM calls, external tools, persistence, or UI.

## Phase 2 — Repository scaffold, configuration, schemas, and interfaces (completed)

**Objective:** create the installable Python package skeleton and testable contracts without implementing agent behavior.

**Files/components affected:** `pyproject.toml`, `.gitignore`, `.env.example`, `src/research_agent/**`, and `tests/**`.

**Implementation work:** use a `src/` package layout; add environment-backed validated settings; define typed Pydantic models for the agreed schemas; create protocol-only component/tool/LLM interfaces in modules matching `ARCHITECTURE.md`; add an argparse CLI placeholder and `python -m` entrypoint; add tests for imports, model construction/validation, CLI startup/help, and settings validation.

**Tests:** `pytest` offline with no credentials or network. Check all component modules import, representative valid and invalid model instances, CLI help/placeholder startup, optional credential-pair validation, and secret-safe settings representation.

**Acceptance criteria:** package imports from `src/`; editable/build metadata is standard `pyproject.toml`; console/module entrypoints start; configuration rejects incomplete credentials without exposing secrets; architecture component module boundaries exist; schemas validate; tests pass offline.

**DO NOT IMPLEMENT YET:** planner logic, plan validation logic, real LLM calls, tool adapters or tool logic, execution/recovery logic, evidence processing/report synthesis, UI, database, external API calls, or dependency installation beyond the already available environment.

## Phase 3 — Planner and plan validation

**Objective:** turn a goal into a validated executable proposal.

**Files/components affected:** planner, LLM client implementation, plan validator implementation, prompt/schema handling, tests, `FAILURE_MODES.md` as needed.

**Implementation work:** implement the provider-neutral `LLMClient` interface and isolated Groq adapter; keep keys in environment settings; define prompt templates as constants; supply the Planner with registered tool metadata/schemas; parse all planner output into strict Pydantic models; validate every step and fallback against `ToolRegistry`; implement deterministic dependency validation and one bounded malformed-output repair. Do not expose tool calling to the model.

**Tests:** fake LLM responses for valid/malformed plans, registered-tool metadata, missing fields, unknown/unregistered tools, invalid arguments, excessive steps, duplicate IDs, missing dependencies, invalid dependencies/cycles, and repair exhaustion; mock the provider transport to check fixed endpoint, JSON mode, environment key use, and absence of tool dispatch without network access.

**Acceptance criteria:** no unvalidated plan reaches execution; one approved plan revision maximum is enforced; tests remain offline by default.

**DO NOT IMPLEMENT YET:** execution engine, tool execution/retries, live search/fetch/calculator behavior, runtime replanning, evidence ranking, or final report synthesis. Only planner/provider retry within the declared model-operation bound is in scope here.

## Phase 4 — Tool adapters and result validation

**Objective:** implement the three approved tools behind the Phase 2 interfaces.

**Files/components affected:** web-search provider adapter, HTTPS fetch adapter, calculator implementation, registry implementation, URL/content safety utilities, fake adapters.

**Implementation work:** use the selected DDGS adapter and resolved resource bounds from `DECISIONS.md`; implement provider-neutral typed tools, public HTTPS validation/redirect safety, normalized responses, and calculator grammar without adapter-owned retries. Search uses the DuckDuckGo backend and requires no search API credential.

**Tests:** deterministic fake providers/transports for success, empty/malformed search, timeout/HTTP failures, URL restrictions/size/content validation, calculator arithmetic and invalid expressions, and unknown tools; no live API calls.

**Acceptance criteria:** all tool arguments/results validate; snippets remain discovery-only; URL/security and resource limits are enforced; adapters cannot dispatch other tools.

**DO NOT IMPLEMENT YET:** multi-step execution, recovery orchestration, evidence ranking, or LLM report synthesis.

## Phase 5 — Execution engine, state, events, and recovery (completed baseline; follow-up in D-031/D-032)

**Objective:** execute validated plans in order and recover through the declared state machine.

**Files/components affected:** execution engine, AgentState transitions, failure handler, event logger, failure-injection harness, tests.

**Implementation work:** enforce legal transitions, stable dependency order, registry argument/result validation, hard dispatch and retry budgets, bounded transient retries, validated fallback and one-plan-revision recovery, failed-step preservation, dependent-step skipping, independent-step continuation, observable event logging, and opt-in one-shot failure injection. D-031/D-032 supersede D-030's deferral of fallback, replanning, and injection.

**Tests:** state transition invariants, sequential/dependency ordering, success/failure/unknown-tool/malformed-result/timeout paths, retry exhaustion, dependent-step skipping, fatal terminal failure, and event ordering.

**Acceptance criteria:** tools can only run through the engine/registry; every failure is observable and retained; dependencies and attempt/run budgets cannot be exceeded; offline recovery tests pass. Ordinary execution returns `SYNTHESIZING`; invalid replans and fatal preconditions enter `FAILED`, while report synthesis later selects report status.

**DO NOT IMPLEMENT YET:** long-term memory, parallel agents, new tools, UI, or scheduled research.

## Phase 6 — Evidence and final report (current phase)

**Objective:** verify sources and synthesize the validated research brief.

**Files/components affected:** evidence store, controller, source validator/ranker, report generator/validator, CLI composition/output, tests, report models if approved changes are needed.

**Implementation work:** attach goal/step provenance to evidence; provide an in-memory validated evidence ledger; wire Planner → PlanValidator → ExecutionEngine → evidence collection → ReportGenerator through AgentController; compose the default Groq/DDGS/tools stack in the CLI; ground final findings in retrieved evidence; project sources deterministically; validate final report references/status; render JSON and Markdown. Source authority ranking and claim-level independent corroboration remain required Phase 6 work.

**Tests:** evidence store validation/deduplication, insufficient/malformed/duplicate evidence, source-invention rejection, controller lifecycle integration with fake planner/tools/LLM, CLI JSON output and JSONL events, failed-step reporting, JSON/Markdown rendering, status rules, and offline synthesis mocks.

**Acceptance criteria:** the CLI runs through the controller without bypassing plan validation or engine state; every reported claim resolves to fetched evidence; unsupported content is omitted or labeled; JSON references and status validate; normal and handled-failure paths are tested offline.

**DO NOT IMPLEMENT YET:** persistence, UI, automated publication, or speculative recommendation features.

## Phase 7 — End-to-end evaluation and assignment materials

**Objective:** demonstrate the take-home requirements with repeatable tests and user documentation.

**Files/components affected:** synthetic fixtures, end-to-end tests, `README.md`, `EVALUATION.md`, `ARCHITECTURE.md`, sample transcripts, one-page design write-up.

**Implementation work:** capture normal, recovered-failure, and insufficient-evidence runs; explain setup, assumptions, limitations, decisions, and future work.

**Tests:** full offline scenario suite, no-key/no-network check, transcript reproducibility, CLI setup smoke test.

**Acceptance criteria:** every assignment requirement maps to a passing test or artifact; two or three transcripts reflect actual behavior and contain no secrets.

**DO NOT IMPLEMENT YET:** features not accepted in `PROJECT_SPEC.md`.

## Phase 8 — Final audit

**Objective:** verify implementation and submission against the contract and rubric.

**Files/components affected:** complete repository.

**Implementation work:** run documented checks; compare behavior/docs; audit citations, secrets, URL policy, limits, logs, and failure status; record final progress.

**Tests:** complete offline suite, packaging/CLI smoke checks, report validation, transcript review, and secret scan.

**Acceptance criteria:** earlier phase gates pass; clean setup works; diagrams match code; multi-tool use, planning trace, failure recovery, structured output, and deliverables are demonstrable.

**DO NOT IMPLEMENT YET:** post-submission enhancements; record them for separate approval.

## Phase 9 — Structured observability (user-requested follow-up increment)

**Objective:** make the approved planning, execution, recovery, and report lifecycle inspectable through validated structured events, JSONL logs, and a concise CLI trace.

**Files/components affected:** `ExecutionEvent`/`EventType`, `AgentState`, `ExecutionEngine`, `ReportGenerator`, `EventLogger`, JSONL sink, CLI trace renderer, tests, and observability/security documentation.

**Implementation work:** include stable event/execution IDs, UTC timestamp, event type, status, optional step/tool IDs, and safe structured metadata; emit lifecycle, tool, failure/recovery, synthesis, and report events; append validated redacted events as JSONL; render only goal/plan/action/outcome/recovery/final-result summaries. This follow-up does not renumber or mark the existing Phase 6–8 gates complete.

**Tests:** offline event generation and ordering, required event fields, JSONL append/parse, secret redaction, visible trace output, and complete existing test suite.

**Acceptance criteria:** each observable execution boundary emits typed events; JSONL has one valid event per line; logs and CLI output exclude secrets and hidden reasoning; recovery and terminal failures remain visible; all offline tests pass.

**DO NOT IMPLEMENT YET:** asynchronous or multi-agent logging, remote log shipping, or persistent application state. The full controller-driven CLI workflow is tracked under Phase 6 and was implemented by the D-036 follow-up.
