# Sequential Implementation Plan

Implement one phase at a time. Do not start a later phase until the current phase's tests and acceptance criteria pass and `PROGRESS.md` records the result.

## Phase 0 — Project scaffold and configuration

**Objective:** establish a runnable Python project shell and safe configuration boundary.

**Files/components affected:** `pyproject.toml`, package entry point, `.env.example`, `.gitignore`, `README.md`, test configuration.

**Implementation work:** create Python 3.11+ package/CLI shell; load environment config without committing secrets; establish output/event channels; document setup and placeholder invocation. No model/tool calls.

**Tests:** CLI help and missing-goal behavior; environment loading with/without optional keys; secret redaction/config validation.

**Acceptance criteria:** clean setup instructions; missing goal exits before external calls; no real key is tracked or logged.

**DO NOT IMPLEMENT YET:** planner, tool adapters, state machine, research logic, failure injection, or report synthesis.

## Phase 1 — Goal, plan schema, and state-machine contracts

**Objective:** accept a goal and produce a validated visible plan without executing it.

**Files/components affected:** input/config modules, plan schema/types, planner interface and Groq adapter, plan validator, state/event definitions.

**Implementation work:** capture one UTC run-start time; parse seven-day default window when omitted; request structured plan; validate step count, IDs, tool names, arguments, dependencies, cycles; emit plan before dispatch.

**Tests:** valid goal/plan; empty goal; malformed planner JSON; unknown tool; invalid arguments; duplicate IDs; dependency cycle; date boundaries/default; mocked Groq failure.

**Acceptance criteria:** only a valid plan reaches `READY`; invalid output is rejected or repaired once and revalidated; trace shows plan validation before tool calls.

**DO NOT IMPLEMENT YET:** live search, page fetching, calculator execution, evidence ranking, or report generation.

## Phase 2 — Tool adapters and result validation

**Objective:** implement the three approved tools behind validated, mockable interfaces.

**Files/components affected:** search adapter/provider interface, HTTPS fetch adapter, calculator adapter, tool schemas, URL/content safety utilities, fake adapters.

**Implementation work:** normalize search results; fetch validated public HTTPS pages; validate redirects/content type/size; extract bounded text/metadata; implement allowlisted decimal arithmetic; return typed outcomes without adapter-owned retries.

**Tests:** valid/empty/malformed search; fetch success, timeout, redirect denial, unsupported content, oversized page; calculator operations and invalid/divide-by-zero input; fake rate limit.

**Acceptance criteria:** inputs/results meet schemas; snippets remain unverified; URL protections and configured limits apply; adapters do not dispatch tools.

**DO NOT IMPLEMENT YET:** autonomous multi-step execution, LLM evidence synthesis, broad source ranking, or sample transcripts.

## Phase 3 — Executor, event trace, and bounded recovery

**Objective:** execute validated plans through the state machine and recover safely.

**Files/components affected:** orchestrator/state machine, dependency scheduler, recovery handler, event recorder, failure-injection harness, `FAILURE_MODES.md`.

**Implementation work:** enforce legal transitions/dependency order; route all failures through recovery; cap each tool step at two total attempts, tool calls at 20/run, model operations at two attempts, plan repair at one/run; support one deterministic simulated failure.

**Tests:** legal/illegal transitions; dependencies; timeout then success; exhaustion; malformed response; one plan repair; injected failure via normal recovery; event order/redaction.

**Acceptance criteria:** no adapter bypasses orchestration; every failure is observable; budgets cannot be exceeded; recovery resumes only through allowed transitions.

**DO NOT IMPLEMENT YET:** topic ranking, final brief, or source-verification claims.

## Phase 4 — Evidence ledger, ranking, and report

**Objective:** turn fetched source material into a cited, bounded research result.

**Files/components affected:** evidence ledger/models, date/source validator, ranker, Groq synthesis interface/prompt, report schema/renderer/validator.

**Implementation work:** store provenance/retrieval dates; enforce time window and two-independent-source target; select up to three developments by relevance, recency, evidence quality, corroboration; validate JSON and set status accurately.

**Tests:** in/out-of-window dates; missing dates; duplicate/related sources; insufficient support; citation mismatch; <3 verified results; malformed report; status/schema checks.

**Acceptance criteria:** every claim links to fetched evidence; unsupported claims are removed or marked unverified; all references validate; evidence insufficiency is disclosed.

**DO NOT IMPLEMENT YET:** additional tools, persistent history, web UI, or scheduled runs.

## Phase 5 — End-to-end evaluation and assignment materials

**Objective:** demonstrate requirements with offline evaluation and reproducible examples.

**Files/components affected:** tests/fixtures, `EVALUATION.md`, `ARCHITECTURE.md`, `README.md`, sample transcripts, one-page design write-up.

**Implementation work:** create synthetic search/page data and mock clients; test full CLI offline; capture two or three runs including normal and recovery; document assumptions, limits, setup, operation.

**Tests:** end-to-end search+fetch success; calculator comparison; empty search; insufficient evidence; API/model failures; injection recovery; report/events; no-key/no-network suite.

**Acceptance criteria:** every assignment requirement maps to a passing test or artifact; transcripts match actual behavior and contain no secrets; tests repeat offline.

**DO NOT IMPLEMENT YET:** unapproved domain expansion, new providers/tools, or features absent from `PROJECT_SPEC.md`.

## Phase 6 — Final audit

**Objective:** verify the submission against the contract and assignment rubric.

**Files/components affected:** entire repository, especially control docs, README, architecture, tests, transcripts.

**Implementation work:** reconcile behavior/spec; run documented checks; inspect a live research run if credentials/provider are available; audit secrets, citations, logs, failure states, limits; resolve doc drift and record status.

**Tests:** complete offline suite; CLI setup/run smoke test; final schema/citation validation; transcript reproducibility; security/secret scan.

**Acceptance criteria:** all phase gates pass; README works cleanly; architecture matches code; multi-tool use, visible plan, graceful injected recovery, structured result, and required artifacts are demonstrable.

**DO NOT IMPLEMENT YET:** post-submission enhancements; record them for separate approval.
