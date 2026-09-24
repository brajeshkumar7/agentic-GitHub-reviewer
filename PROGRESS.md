# Project Progress

All phases are tracked here. A phase is complete only after its acceptance criteria and tests/reviews are evidenced.

## Phases

- [x] **Phase 0 — Project control documents:** created and reviewed the nine engineering-control documents.
- [x] **Phase 1 — Technical architecture contract:** finalized the requested components, schemas, lifecycle, recovery, trace, and diagrams in `ARCHITECTURE.md`; recorded decisions in `DECISIONS.md`.
- [x] **Phase 2 — Repository scaffold, configuration, schemas, and interfaces:** package skeleton, settings, models, protocols, placeholder CLI, and offline tests completed.
- [x] **Phase 3 — Planner and plan validation:** Groq LLM adapter, strict planner schemas, prompt templates, deterministic proposal validation, and bounded repair completed.
- [x] **Phase 4 — Tool adapters and result validation:** DDGS-backed web search, safe HTTPS fetch, calculator, typed registry, and offline failure tests completed. D-037 replaces the earlier Brave provider choice D-026.
- [x] **Phase 5 — Execution engine, state, events, and recovery baseline:** deterministic orchestration, validated tool dispatch, bounded retry, step tracking, and event logging completed. Recovery follow-up D-031/D-032 adds bounded retry/fallback/replan and injected-failure handling.
- [ ] **Phase 6 — Evidence and final report:** source verification and validated report generation.
- [ ] **Phase 7 — End-to-end evaluation and assignment materials:** offline scenarios, README, transcripts, short write-up.
- [ ] **Phase 8 — Final audit:** full acceptance, security, reproducibility, and documentation review.
- [x] **Phase 9 — Structured observability increment:** stable typed execution events, redacted JSONL sink, CLI trace renderer, and offline observability tests completed (D-035). This follow-up does not mark earlier unfinished gates complete.

## Current phase gate

- **D-046 synthesis provider boundary:** user supplied live evidence that search
  and two fetches succeeded; final synthesis failed with an undisclosed provider
  category. Added safe category/attempt reporting and bounded transient retries.
  Full offline suite: **121 passed in 1.14s**. Live synthesis remains unverified.
  The supplied sources lack publication dates and do not establish the requested
  recent RAG developments; research-quality gates remain incomplete.

- **D-045 HTTPS transport fix:** removed obsolete Python 3.13 handler attribute
  access and corrected the shadowed DNS-pinning connector. Offline suite:
  **117 passed in 1.11s**, using `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`.
  New tests check handler delegation, numeric public-IP socket connection with
  original TLS hostname, and private-address rejection before socket creation.
  Live research completion remains unverified; existing gates remain incomplete.

- **D-044 fetch provenance:** unsupported planner literal URLs now enter bounded
  repair before execution; PlanValidator independently checks primary/fallback
  URL provenance. Existing executor safeguards remain intact. Offline suite:
  **114 passed in 1.33s** (`.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`).
  Added guessed-URL repair and goal-supplied URL cases; verified validator rejection
  and executor protection if validation is bypassed. Live success remains pending.

- **D-043 discovered URL binding:** added plan-only search-result references,
  direct search dependency validation, deterministic resolution before fetch,
  and selected-tool validation feedback without unrelated union errors.
  Full offline suite: **112 passed in 0.86s** using
  `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`.
  Covered reference-based search/fetch/report success, unavailable result with
  no fetch dispatch, malformed references, and invalid-URL feedback. No live
  API calls or secret-file reads. Existing incomplete phase gates remain open.

- **D-042 planner repair diagnostics:** the latest user run exhausted local
  validation, not an observed HTTP rate-limit failure. Added safe field/code
  feedback to the repair request, retry trace, and terminal report; clarified
  the planner output contract. Offline suite: `.venv\Scripts\python.exe -m
  pytest -q -p no:cacheprovider` — **104 passed in 0.96s**. No live API calls
  made; a successful live plan and the existing Phase 6 gates remain pending.

- **D-041 RCA/fix verified offline:** the saved run shows malformed planner output followed immediately by a repair request rejected with 429. Removed duplicate schema transmission (synthetic user-message size 12,256 → 8,055 bytes), honored bounded Retry-After, paced malformed repair, corrected rate-limit reporting, and removed duplicated trace text. `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`: **102 passed in 3.04s**. This suite run supersedes the older pending offline-verification notes below, including D-037 through D-040. No live API calls, dependency installations, or secret-file reads were made for this fix; a completed live research run and Phase 6 evidence-quality gates remain unverified/incomplete.

- Current documented gate remains **Phase 6 — Evidence and final report**. The user's “Phase 7 recovery” increment maps to D-031/D-032; the user's “Phase 8 evidence/report” request is tracked as D-034; the user's “Phase 9 structured observability” request is tracked as D-035. Existing phase numbers are unchanged.
- Search-provider migration D-037 is implemented in the current worktree. The default search adapter now uses DDGS with the DuckDuckGo backend and needs no search key. Its new dependency is declared but was not installed in this workspace; install project dependencies before using live search. Offline provider tests were updated but have not been run in this increment.
- Groq GPT-OSS planner compatibility adjustment D-038 is implemented: GPT-OSS requests use low reasoning effort and the planner prompt explicitly uses lowercase `json`. The user's direct low-effort probe succeeded; the live application rerun and offline regression suite remain unverified.
- Planner failure reports now preserve a sanitized Groq HTTP status and provider error-code identifier (D-039), so the next CLI run should distinguish JSON validation, authentication, rate-limit, and other HTTP failures without exposing raw provider payloads. Regression tests and live rerun remain pending.
- Groq requests now include the explicit User-Agent validated by the user's successful Python urllib probe (D-040). The CLI retry and regression suite remain pending.
- Planner, tools, execution, evidence collection, controller orchestration, and CLI output are mock-tested; no live external API calls were made. Fetched pages now enter the evidence ledger with step provenance and retrieval verification. Source authority ranking, claim-level independent corroboration, complete rubric scenarios, and sample transcripts remain incomplete.
- Environment observed: Python 3.13, Pydantic 2.10.6, pytest 9.0.3 already available; no dependencies installed.

## Phase evidence log

| Phase | Status | Test/acceptance evidence | Notes |
|---|---|---|---|
| 0 | Complete | Control-document inventory/review | Documentation-only. |
| 1 | Complete | Architecture and decision review | Documentation-only; no application tests. |
| 2 | Complete | `pytest -p no:cacheprovider`: 11 passed; CLI `python -m research_agent --help` smoke-tested offline; `git diff --check` clean. | No dependencies installed; no live API calls. |
| 3 | Complete | `pytest -p no:cacheprovider`: full suite 49 passed; planner/validator tests cover registry metadata, schema validation, malformed output and repair bound, unknown/unregistered tools, invalid arguments, missing/duplicate IDs, missing/circular dependencies, step limits, plan revision, and absence of tool dispatch. | Planner catalog is sourced from `ToolRegistry`, rejects tools absent from it, and `PlanValidator` checks step/fallback arguments against registered schemas. Recorded in D-029. No live LLM/API calls. |
| 4 | Complete | `pytest -p no:cacheprovider`: full suite 49 passed at original provider implementation; D-037 adds replacement provider tests (not run in this increment). | The original provider was Brave; D-037 replaces it with DDGS. The remaining tool boundaries are unchanged. No live API calls. |
| 5 | Complete | Baseline at phase completion: `pytest -p no:cacheprovider`: 57 passed. Follow-up recovery coverage is recorded in the recovery increment row below. | Initial baseline details are retained historically; D-031/D-032 supersede D-030's recovery deferral. No live API calls. |
| Recovery increment (user-designated Phase 7) | Implemented | Baseline recovery tests cover injected timeout/malformed-response recovery, two retries then explicit exhaustion, declared fallback, one validated replan, and terminal invalid-replan failure. | The calculator-only test reports a limitation because it has no source evidence; it does not fabricate a completed research report. The implementation increment did not complete documented Phase 6 report synthesis or Phase 7 assignment materials. No live APIs. Decisions D-031–D-033. |
| Evidence/report increment (user-designated Phase 8) | Implemented; documented Phase 6 gate remains incomplete | `pytest -q -p no:cacheprovider`: full suite 73 passed at that increment. Tests cover successful JSON/Markdown output, failed-step reporting, missing/unverified evidence, idempotent/conflicting duplicate evidence, malformed evidence, URL/source fabrication rejection, and unknown evidence references. | Evidence ledger and report generator are implemented. Controller integration was completed in D-036; source authority ranking, claim-level corroboration, and final audit remain pending. No live APIs. D-034. |
| Structured observability increment (user-designated Phase 9) | Implemented | `pytest -q -p no:cacheprovider`: full suite 76 passed at that increment. Observability tests cover lifecycle event generation/fields, JSONL append and parse, redaction of secret-like values, and CLI plan/action/recovery trace rendering; report tests verify synthesis/final-report/completion events. | Added typed event names, execution IDs, UTC timestamps, metadata/status, and redacting JSONL plus trace renderers. The controller-driven CLI was completed in D-036. No external APIs. D-035. |
| Controller/CLI integration (D-036) | Implemented; Phase 6 gate remains incomplete | `pytest -q -p no:cacheprovider`: full suite 82 passed. Offline integration covers goal/window resolution, plan/validate/execute flow, search/fetch mocks, evidence ledger population, final synthesis, ordered trace events, planner failure reports, bounded planner retry visibility, CLI JSON output, CLI JSONL logging, and rejection of fetch URLs absent from the goal/search results. `git diff --check` reported no whitespace errors. | The CLI now composes the real configured Groq/DDGS adapters and approved tools. Fetched page evidence is retrieval-verified; source authority ranking and claim-level corroboration remain explicit limitations. No external APIs were called. |
| Search provider migration (D-037) | Implemented; verification pending | Test coverage updated for normalized DDGS results, supported time-window filter mapping, malformed results, timeout, and rate-limit failures. Tests not run in this increment. | Replaced Brave, removed `BRAVE_SEARCH_API_KEY` from configuration and `.env.example`, and declared `ddgs>=9.16,<10`. No live API calls or dependency installation. |
| 6 | Incomplete | — | — |
| 7 | Incomplete | — | — |
| 8 | Incomplete | — | — |
