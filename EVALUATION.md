# Evaluation Plan

Evaluation maps take-home requirements to concrete demonstrations. Default tests use synthetic data and mocked Groq/search/fetch clients; they require no key, paid inference, or live network.

## Assignment requirement mapping

| Requirement | Implementation evidence | Test or artifact |
|---|---|---|
| Accept high-level natural-language goal | CLI accepts one goal and creates immutable run context | Normal-goal test; empty goal rejected before external calls |
| Autonomously decompose into steps | Groq adapter returns text; Planner validates strict `Plan`/`PlanStep` schemas and PlanValidator binds the proposal to the goal | Offline fake planner tests cover valid output, malformed output and one repair, missing fields, unknown tools, >8 steps, and invalid dependencies |
| Visible structured planning trace | Validated plan/state/tool events emitted before/during execution | Transcript asserts plan appears before first tool call |
| Execute plan step by step | `ExecutionEngine` runs a validated plan in stable topological order through `ToolRegistry` | Offline engine tests assert sequential calls, dependency gating, result retention, and `SYNTHESIZING` handoff |
| Use at least two tools | Successful research uses web search and page fetch; calculator available for arithmetic | End-to-end test asserts search+fetch; quantitative fixture asserts calculator |
| Safe registered tool execution | `ToolRegistry` validates tool names, arguments, metadata and normalized outputs; each tool returns a `ToolResult` | Offline mocks assert registration/metadata, unknown-tool and invalid-argument failures, timeout/HTTP/malformed/empty search, safe URL rejection, content bounds, and invalid calculator grammar |
| Detect tool/execution failures | Typed tool results, preserved step failures, and ordered state/tool events in `AgentState` | Offline engine tests cover failed execution, unknown/unregistered tool, malformed result, timeout, retry exhaustion, dependency skip, and fatal `FAILED` state |
| Recover from induced failure | `FailureInjector` emits a typed one-shot timeout or malformed-response failure; `FailureHandler` selects bounded recovery | `tests/test_failure_recovery.py::test_injected_timeout_recovers_and_produces_successful_structured_report` asserts failure → retry → success and a validated `COMPLETED` report |
| Structured final result | Versioned JSON report with brief, sources, plan, execution, failures, limitations | Schema, citation-reference, status, serialization tests |
| Tests and documentation | Offline suite, setup/run README, control docs, architecture | Clean setup check and offline suite |
| Architecture diagram | Mermaid diagram in `ARCHITECTURE.md` | Manual comparison with implemented state transitions |
| 2–3 sample transcripts | Normal, recovered-failure, insufficient-evidence runs | Reproducible with fakes and matching actual CLI output |
| One-page write-up | Decisions, limitations, and future work summary | Reviewer checks length and consistency with decisions |

## Synthetic fixture set

- Search results with relevant, irrelevant, duplicate, stale, missing-date, and empty candidate sets.
- Fake Brave API envelopes, malformed payloads, HTTP status errors, and timeouts; fake page responses for supported/unsupported content, oversized pages, redirects, and unsafe DNS destinations.
- Pages representing primary sources, independent corroboration, copied reporting, contradictory claims, malformed content, unsafe links, and missing publication dates.
- Quantitative comparison with known values to verify calculator behavior.
- Fake Groq responses: valid plans/reports, malformed JSON, invalid tool names, dangling citations, transient/permanent failures.
- Mocked Groq HTTP transport: assert configured environment model/key use, fixed provider endpoint, JSON response mode, bounded response size, no tool definitions, and sanitized errors without live network access.
- One-shot injected timeout and malformed response, persistent timeout exhaustion, semantic replan success/failure, invalid URL, and unsafe URL outcomes. Tests inject settings and fake tools; no external APIs or credentials are used.

## Required scenarios

1. **Normal research:** plan precedes calls; search and fetch run; developments cite verified evidence; JSON references resolve.
2. **Three-tool run:** goal needs a numerical comparison; calculator result is correct and inputs/evidence are traceable.
3. **Planning failure:** malformed output is repaired once then validated, or fails before any tool call.
4. **Empty/weak evidence:** no invented results; return fewer items and explain why.
5. **Injected recovery demo:** run with `AGENT_INJECT_FAILURE=true`, `AGENT_FAILURE_MODE=tool_timeout`, and `AGENT_FAILURE_TOOL=calculator`. Assert one `FAILURE_INJECTED`, visible `RECOVERY_STARTED` and `RETRY_ATTEMPTED`, a second successful tool call, and a schema-valid `COMPLETED` report. Repeat with `AGENT_FAILURE_MODE=malformed_tool_response`; both are deterministic, one-shot, and offline.
6. **Semantic recovery:** an empty-result fixture selects a declared fallback or one validated revision. A malformed revision enters terminal `FAILED` and is not executed.
7. **Exhaustion:** persistent errors stop after 3 calls per logical step (2 retries), preserve `RETRY_EXHAUSTED`, and return a partial/failed report with an explicit limitation.
8. **Security:** page prompt injection cannot change instructions/tool permissions; unsafe URL/redirect is rejected; secret strings never appear in logs/report.
9. **Offline mode:** end-to-end tests run using fakes with no network or credentials.

## Quality review

- Confirm UTC cutoff is stable and recent developments fall within it.
- Check source independence/reliability rationale; snippets are never verification citations.
- Ensure wording separates sourced claims from interpretation and marks uncertainty.
- Check retry/tool/model limits, states, and report status against the spec.
- Inspect transcripts for ordering, readability, recovery evidence, and secret redaction.
