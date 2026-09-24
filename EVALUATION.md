# Evaluation Plan

Evaluation maps take-home requirements to concrete demonstrations. Default tests use synthetic data and mocked Groq/search/fetch clients; they require no key, paid inference, or live network.

## Assignment requirement mapping

| Requirement | Implementation evidence | Test or artifact |
|---|---|---|
| Accept high-level natural-language goal | CLI accepts one goal and creates immutable run context | Normal-goal test; empty goal rejected before external calls |
| Autonomously decompose into steps | Groq adapter returns text; Planner validates strict `Plan`/`PlanStep` schemas and PlanValidator binds the proposal to the goal | Offline fake planner tests cover valid output, malformed output and one repair, missing fields, unknown tools, >8 steps, and invalid dependencies |
| Visible structured planning trace | Validated plan/state/tool events emitted before/during execution | Transcript asserts plan appears before first tool call |
| Structured observability and JSONL | Typed execution events carry unique IDs, execution ID, UTC timestamp, event type, status, and metadata; logger redacts sensitive values before JSONL serialization | `tests/test_observability.py` checks lifecycle event generation, JSONL append/parse, secret redaction, and CLI trace ordering/formatting |
| Controller-driven CLI workflow | `AgentController` coordinates the configured planner, validator, engine, evidence ledger, and report generator; `research-agent GOAL [--events-jsonl PATH]` emits JSON to stdout and trace to stderr | `tests/test_controller.py` runs a synthetic search/fetch/synthesis workflow offline; `tests/test_scaffold.py` verifies handled configuration failure and CLI JSONL output |
| Execute plan step by step | `ExecutionEngine` runs a validated plan in stable topological order through `ToolRegistry` | Offline engine tests assert sequential calls, dependency gating, result retention, and `SYNTHESIZING` handoff |
| Use at least two tools | Successful research uses web search and page fetch; calculator available for arithmetic | End-to-end test asserts search+fetch; quantitative fixture asserts calculator |
| Safe registered tool execution | `ToolRegistry` validates tool names, arguments, metadata and normalized outputs; each tool returns a `ToolResult` | Offline mocks assert registration/metadata, unknown-tool and invalid-argument failures, timeout/HTTP/malformed/empty search, safe URL rejection, content bounds, and invalid calculator grammar |
| Detect tool/execution failures | Typed tool results, preserved step failures, and ordered state/tool events in `AgentState` | Offline engine tests cover failed execution, unknown/unregistered tool, malformed result, timeout, retry exhaustion, dependency skip, and fatal `FAILED` state |
| Recover from induced failure | `FailureInjector` emits a typed one-shot timeout or malformed-response failure; `FailureHandler` selects bounded recovery | `tests/test_failure_recovery.py::test_injected_timeout_recovers_and_report_discloses_missing_source_evidence` asserts failure → retry → success and honest partial status when no research evidence exists |
| Structured final result | `EvidenceStore` validates and scopes evidence; `ReportGenerator` returns the requested JSON and Markdown representations; source rows are projected from the ledger | `tests/test_report_generator.py` covers supported synthesis, failed steps, missing/unverified evidence, duplicate/malformed evidence, fabricated source rejection, and both renderings |
| Tests and documentation | Offline suite, setup/run README, control docs, architecture | Clean setup check and offline suite |
| Architecture diagram | Mermaid diagram in `ARCHITECTURE.md` | Manual comparison with implemented state transitions |
| 2–3 sample transcripts | Normal, recovered-failure, insufficient-evidence runs | Reproducible with fakes and matching actual CLI output |
| One-page write-up | Decisions, limitations, and future work summary | Reviewer checks length and consistency with decisions |

## Synthetic fixture set

- Search results with relevant, irrelevant, duplicate, stale, missing-date, and empty candidate sets.
- Fake DDGS result lists, malformed entries, rate-limit/timeout failures; fake page responses for supported/unsupported content, oversized pages, redirects, and unsafe DNS destinations.
- Pages representing primary sources, independent corroboration, copied reporting, contradictory claims, malformed content, unsafe links, and missing publication dates.
- Quantitative comparison with known values to verify calculator behavior.
- Fake Groq responses: valid plans/reports, malformed JSON, invalid tool names, dangling citations, transient/permanent failures.
- Mocked Groq HTTP transport: assert configured environment model/key use, fixed provider endpoint, JSON response mode, bounded response size, no tool definitions, and sanitized errors without live network access.
- One-shot injected timeout and malformed response, persistent timeout exhaustion, semantic replan success/failure, invalid URL, unsafe URL, and evidence/report fixtures. Tests inject settings and fake clients; no external APIs or credentials are used.

## Required scenarios

1. **Normal research:** plan precedes calls; search and fetch run; developments cite verified evidence; JSON references resolve.
2. **Three-tool run:** goal needs a numerical comparison; calculator result is correct and inputs/evidence are traceable.
3. **Planning failure:** malformed output is repaired once then validated, or fails before any tool call.
4. **Empty/weak evidence:** no invented results; return fewer items and explain why.
5. **Injected recovery demo:** run with `AGENT_INJECT_FAILURE=true`, `AGENT_FAILURE_MODE=tool_timeout`, and `AGENT_FAILURE_TOOL=calculator`. Assert one `FAILURE_INJECTED`, visible `RECOVERY_STARTED` and `RETRY_ATTEMPTED`, and a second successful tool call. If no source evidence was collected, the final report must be `partial`/`failed` and disclose that gap rather than claiming a completed research brief.
6. **Semantic recovery:** an empty-result fixture selects a declared fallback or one validated revision. A malformed revision enters terminal `FAILED` and is not executed.
7. **Exhaustion:** persistent errors stop after 3 calls per logical step (2 retries), preserve `RETRY_EXHAUSTED`, and return a partial/failed report with an explicit limitation.
8. **Security:** page prompt injection cannot change instructions/tool permissions; unsafe URL/redirect is rejected; secret strings never appear in logs/report.
9. **Offline mode:** end-to-end tests run using fakes with no network or credentials.
10. **Report rendering:** with synthetic verified evidence, fake synthesis returns findings tied to evidence IDs; JSON and Markdown contain the same plan, observed evidence, generated findings, failures/recoveries, and limitations. A synthesis response containing its own source list or unknown evidence ID is rejected.

## Quality review

- Rate-limit regression: mock HTTP 429 with valid, missing, invalid, zero, HTTP-date, and over-budget Retry-After. Assert ordered call/wait/call behavior, one retry maximum, no early retry of a long cooldown, no retries for 401, and no raw response/secret leakage. Replay malformed output followed by 429 and assert the shared two-attempt budget prevents a third call. Controller tests assert `rate_limit`, retryable cause, visible delay, failed report, and zero tool dispatches. Schema-deduplication tests assert equivalent schema content and no mutation of caller payload.

- Confirm UTC cutoff is stable and recent developments fall within it.
- Check source independence/reliability rationale; snippets are never verification citations.
- Ensure wording separates sourced claims from interpretation and marks uncertainty.
- Check retry/tool/model limits, states, and report status against the spec.
- Keep retrieval verification distinct from source authority ranking and claim-level corroboration; current reports disclose that remaining limitation.
- Inspect transcripts for ordering, readability, recovery evidence, and secret redaction.
# Planner repair feedback regression (D-042)

D-046 synthesis tests cover transient retry success, exhausted 429, over-budget
Retry-After, non-retryable provider failure, visible retry events, and preserved
evidence with no fabricated findings. Full offline suite: 121 passed.

D-045 adds `tests/test_fetch_transport.py`: real handler delegation and connection
initialization with mocked sockets, correct public-IP destination and TLS hostname,
and private-IP rejection before socket creation. Full offline suite: 117 passed.
These tests close a coverage gap in earlier injected-transport tests; live page
availability and successful live research are not established by this suite.

D-044 regressions cover a guessed HTTPS URL repaired to a search reference,
a literal URL explicitly supplied in the goal, independent PlanValidator
rejection, and executor authorization despite bypassed validation. Full offline
suite: 114 passed; no live APIs were called.

D-043 adds offline tests for a reference-based search/fetch/final-report run
without a source URL supplied to the planner, missing-result failure without
fetch dispatch, valid reference parsing, rejected missing dependencies/wrong
tools/negative indices/extra fields, and selected-tool-only URL diagnostics.
Full suite: 112 passed. Live model compliance remains unverified.

Offline tests cover missing-field feedback followed by a valid repaired plan,
redaction of arbitrary extra-field names and values in public diagnostics,
bounded goal-ID mismatch failure, and validation details in terminal reports.
The full suite passed: 104 tests. This proves the deterministic repair contract;
it does not establish live model compliance or successful end-to-end research.

