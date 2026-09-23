# Architectural Decisions

This log records accepted initial decisions and unresolved choices that block implementation. Update it before changing an accepted architectural choice.

## Accepted decisions

| ID | Decision | Rationale |
|---|---|---|
| D-001 | Domain: Autonomous Research Intelligence Agent for recent developments. | Selected assignment example supports planning, live research, verification, comparison, and synthesis. |
| D-002 | Python 3.11+ CLI, one natural-language goal per run. | Python is permitted by the assignment; CLI is simple to run and demonstrate. |
| D-003 | Groq for planning/synthesis; `GROQ_API_KEY` and `GROQ_MODEL` from environment. | Groq was selected earlier by the user; configurable model avoids hard-coding an identifier. |
| D-004 | Initial tools: web search, HTTPS page fetch, deterministic calculator. | Search discovers candidates, fetch verifies sources, calculator handles requested numerical comparison. Successful research uses search and fetch; calculator runs when arithmetic is relevant. |
| D-005 | Planner proposes structured steps; separate validator authorizes; one orchestrator owns execution/recovery. | Prevents model output from directly calling tools or skipping state transitions. |
| D-006 | Relative dates use one UTC run-start timestamp; default window is the previous seven days. | Makes “latest” testable and prevents cutoff drift during a run. |
| D-007 | Each reported development targets two independent fetched sources, preferring a primary source plus independent corroboration. | Snippets are not evidence; provenance supports verification. If the threshold is unmet, disclose insufficiency and report fewer items. |
| D-008 | Versioned JSON report plus concise structured event trace; no hidden model reasoning. | Supports machine-readable results and visible orchestration. |
| D-009 | Hard bounds: 2 total attempts/tool step, 20 tool invocations/run, 2 attempts/model operation, at most one plan repair. | Prevents loops and makes outcomes deterministic. |
| D-010 | Synthetic fixtures and fake clients for offline evaluation. | Tests are reproducible without keys, paid inference, or live network access. |
| D-011 | One-shot failure injection for the sample recovery demonstration. | Repeatably exercises the normal recovery path. |

## Open decisions required before coding

- **Search provider/API:** choose a concrete provider and confirm student/free access, key setup, request/response shape, and rate limits. Keep the tool interface provider-neutral until resolved.
- **Resource limits:** set connect/read timeouts, maximum response/page bytes, result count, fetched page count, and model input/output token bounds. Call/step/retry counts are fixed in the spec; byte/time/token limits need values before adapters are coded.
- **Source reliability rule:** the contract prefers primary sources and requires source independence, but an operational method for classifying publishers/domains and independence must be reviewed before evidence ranking is coded. Search ranking alone cannot confer reliability.

## Configuration reference

- `GROQ_API_KEY`: secret; required for live model calls, never committed or logged.
- `GROQ_MODEL`: required model identifier for live calls; environment-configured, not hard-coded.
- Search-provider name/key: record after provider selection; keep key in environment configuration.

Follow current [Groq API compatibility documentation](https://console.groq.com/docs/openai) for endpoint/request details when implementing the client.
