# Evaluation Plan

Evaluation maps take-home requirements to concrete demonstrations. Default tests use synthetic data and mocked Groq/search/fetch clients; they require no key, paid inference, or live network.

## Assignment requirement mapping

| Requirement | Implementation evidence | Test or artifact |
|---|---|---|
| Accept high-level natural-language goal | CLI accepts one goal and creates immutable run context | Normal-goal test; empty goal rejected before external calls |
| Autonomously decompose into steps | Groq emits structured plan with tools, args, dependencies, success criteria | Mocked planner yields multi-step plan; invalid cases exercise validator |
| Visible structured planning trace | Validated plan/state/tool events emitted before/during execution | Transcript asserts plan appears before first tool call |
| Execute plan step by step | Orchestrator runs dependency-ordered steps | Assert tool call ordering and prerequisite gating |
| Use at least two tools | Successful research uses web search and page fetch; calculator available for arithmetic | End-to-end test asserts search+fetch; quantitative fixture asserts calculator |
| Detect tool/execution failures | Typed errors and state-machine failure events | Timeout, invalid response, empty results, blocked fetch, calculator, model, dependency cases |
| Recover from induced failure | One-shot injection uses normal `RECOVERING` path | Injected timeout asserts bounded retry, recovery event, accurate final status |
| Structured final result | Versioned JSON report with brief, sources, plan, execution, failures, limitations | Schema, citation-reference, status, serialization tests |
| Tests and documentation | Offline suite, setup/run README, control docs, architecture | Clean setup check and offline suite |
| Architecture diagram | Mermaid diagram in `ARCHITECTURE.md` | Manual comparison with implemented state transitions |
| 2–3 sample transcripts | Normal, recovered-failure, insufficient-evidence runs | Reproducible with fakes and matching actual CLI output |
| One-page write-up | Decisions, limitations, and future work summary | Reviewer checks length and consistency with decisions |

## Synthetic fixture set

- Search results with relevant, irrelevant, duplicate, stale, missing-date, and empty candidate sets.
- Pages representing primary sources, independent corroboration, copied reporting, contradictory claims, malformed content, unsafe links, and missing publication dates.
- Quantitative comparison with known values to verify calculator behavior.
- Fake Groq responses: valid plans/reports, malformed JSON, invalid tool names, dangling citations, transient/permanent failures.
- Injected timeout, invalid response, retry exhaustion, and unsafe URL outcomes.

## Required scenarios

1. **Normal research:** plan precedes calls; search and fetch run; developments cite verified evidence; JSON references resolve.
2. **Three-tool run:** goal needs a numerical comparison; calculator result is correct and inputs/evidence are traceable.
3. **Planning failure:** malformed output is repaired once then validated, or fails before any tool call.
4. **Empty/weak evidence:** no invented results; return fewer items and explain why.
5. **Tool recovery:** transient timeout retries within budget; injected failure appears in transcript and execution record.
6. **Exhaustion:** persistent errors stop at exact limits and return partial/failed.
7. **Security:** page prompt injection cannot change instructions/tool permissions; unsafe URL/redirect is rejected; secret strings never appear in logs/report.
8. **Offline mode:** end-to-end tests run using fakes with no network or credentials.

## Quality review

- Confirm UTC cutoff is stable and recent developments fall within it.
- Check source independence/reliability rationale; snippets are never verification citations.
- Ensure wording separates sourced claims from interpretation and marks uncertainty.
- Check retry/tool/model limits, states, and report status against the spec.
- Inspect transcripts for ordering, readability, recovery evidence, and secret redaction.
