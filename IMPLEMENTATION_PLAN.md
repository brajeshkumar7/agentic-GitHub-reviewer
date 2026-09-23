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

**Implementation work:** implement the provider-neutral `LLMClient` interface and isolated Groq adapter; keep keys in environment settings; define prompt templates as constants; parse all planner output into strict Pydantic models; implement deterministic plan validation and one bounded malformed-output repair. Do not expose tool calling to the model.

**Tests:** fake LLM responses for valid/malformed plans, missing fields, unknown tools, invalid arguments, excessive steps, invalid dependencies/cycles, and repair exhaustion; mock the provider transport to check fixed endpoint, JSON mode, environment key use, and absence of tool dispatch without network access.

**Acceptance criteria:** no unvalidated plan reaches execution; one approved plan revision maximum is enforced; tests remain offline by default.

**DO NOT IMPLEMENT YET:** execution engine, tool execution/retries, live search/fetch/calculator behavior, runtime replanning, evidence ranking, or final report synthesis. Only planner/provider retry within the declared model-operation bound is in scope here.

## Phase 4 — Tool adapters and result validation

**Objective:** implement the three approved tools behind the Phase 2 interfaces.

**Files/components affected:** web-search provider adapter, HTTPS fetch adapter, calculator implementation, registry implementation, URL/content safety utilities, fake adapters.

**Implementation work:** use the selected Brave adapter and resolved resource bounds from `DECISIONS.md`; implement provider-neutral typed tools, public HTTPS validation/redirect safety, normalized responses, and calculator grammar without adapter-owned retries.

**Tests:** deterministic fake providers/transports for success, empty/malformed search, timeout/HTTP failures, URL restrictions/size/content validation, calculator arithmetic and invalid expressions, and unknown tools; no live API calls.

**Acceptance criteria:** all tool arguments/results validate; snippets remain discovery-only; URL/security and resource limits are enforced; adapters cannot dispatch other tools.

**DO NOT IMPLEMENT YET:** multi-step execution, recovery orchestration, evidence ranking, or LLM report synthesis.

## Phase 5 — Execution engine, state, events, and recovery (current phase)

**Objective:** execute validated plans in order and recover through the declared state machine.

**Files/components affected:** execution engine, AgentState transitions, failure handler, event logger, failure-injection harness, tests.

**Implementation work:** enforce legal transitions, dependency order, hard budgets, retry/fallback/replan policy, and deterministic one-shot failure injection.

**Tests:** state transition invariants, step ordering, retry/fallback/replan outcomes, exhaustion, failure injection, event ordering/redaction.

**Acceptance criteria:** tools can only run through the engine/registry; every failure is observable; budgets cannot be exceeded; offline recovery tests pass.

**DO NOT IMPLEMENT YET:** long-term memory, parallel agents, new tools, UI, or scheduled research.

## Phase 6 — Evidence and final report

**Objective:** verify sources and synthesize the validated research brief.

**Files/components affected:** evidence store, source validator/ranker, report generator/validator, tests, report models if approved changes are needed.

**Implementation work:** attach provenance, enforce the requested time window and evidence references, rank up to three supported developments, generate and validate the structured report and status.

**Tests:** independent-source/citation/date cases, insufficient or contradictory evidence, malformed report, status rules, and offline synthesis mocks.

**Acceptance criteria:** every reported claim resolves to fetched evidence; unsupported content is omitted or labeled; JSON references and status validate.

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
