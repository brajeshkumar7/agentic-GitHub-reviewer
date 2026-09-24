# Failure Modes and Recovery Contract

All tool failures pass through `FailureHandler`; adapters return structured results and never retry. The executor records the failed call, emits recovery events, and follows the deterministic policy below. No raw provider body or secret is included in event summaries.

## Classification

| Class | Categories | Policy |
|---|---|---|
| Retryable | Timeout, temporary HTTP 5xx/rate limit, transient provider error, explicitly retryable malformed response | Retry the same validated call, at most twice per logical step, if the per-run limit allows. |
| Non-retryable | Invalid arguments, unknown tool, invalid plan, unsafe URL/security violation, authentication/configuration failure, deterministic calculator error | Do not retry. Use no fallback unless the failure is separately classified as an eligible semantic source issue. Preserve the failure. |
| Recoverable semantic | Empty/insufficient search result, unavailable source, page-specific not-found/unsupported content | Use a validated fallback if declared; otherwise request the one permitted validated plan revision when available; otherwise fail the step. |
| Terminal | Retry budget exhausted, invalid plan after replanning, run dispatch budget exhausted, unrecoverable configuration/state invariant | Preserve the cause and stop the run when no trustworthy execution can continue. Failed steps may leave the run in `SYNTHESIZING` so a report can return `PARTIAL` with a limitation. |

## Expected failures

| Failure | Detection | Recovery and result |
|---|---|---|
| Tool timeout | Adapter deadline or injected timeout | Retry up to two times; after exhaustion record `RETRY_EXHAUSTED`, mark step failed and skip dependents. |
| Invalid tool response | Pydantic/result provenance/output-schema validation | Reject it; retry only when the failure is explicitly classified as transient. Never treat malformed data as evidence. |
| Malformed planner output | Invalid JSON/schema or invalid plan graph/tool arguments | Planner’s separately bounded model repair may run before validation. Invalid plan after the single runtime replan is terminal `FAILED`. |
| Empty search results | Valid search response with zero results | Use prevalidated fallback query, then one validated replan when available; otherwise retain a source-gap limitation. |
| DDGS search throttle/outage | The DuckDuckGo backend rejects or times out a DDGS request | Normalize rate limits/timeouts as typed retryable failures; use the ordinary bounded FailureHandler policy. There is no search API credential to refresh. |
| URL fetch failure | Timeout, HTTP status, unsafe redirect or unsupported content | Retry transient timeout/5xx; a safe alternate URL can be used only if declared and validated. Security failures are never retried or bypassed. |
| Calculator failure | Restricted expression/operation validation | Permanent for the same arguments; preserve failure and report the unavailable calculation. |
| LLM/API failure | Provider timeout/status/invalid response | Retry transient failures within the separate model-operation cap; authentication/configuration errors are terminal. Never log API keys. |
| Insufficient evidence | Evidence checks cannot verify or corroborate a claim | Search/fetch only within the plan, fallback and single replan limits; omit unsupported claims and explain the gap. |
| Execution step failure | Tool failure or dispatch/result validation failure | Route through `FailureHandler`, preserve step status and failure, skip dependent steps, and continue independent work. |
| Retry exhaustion | Two retries or global dispatch ceiling consumed | No further tool call. Mark the logical step failed and state the exhausted limit explicitly. |
| Invalid replan | Replanner returns malformed/unknown-tool/invalid-dependency plan | Revalidate through `PlanValidator`; a rejected revision makes lifecycle `FAILED`. |
| Configuration/security failure | Missing required setting, unsafe URL, invalid tool name/arguments | Do not retry or execute; return controlled terminal/step failure. |
| Invalid event or JSONL write failure | Event schema rejects malformed fields, or the configured event-log path is unavailable/unwritable | Reject malformed events. Surface filesystem/serialization errors to the caller; never silently drop an event or log a raw exception payload. |
| Planning/API configuration failure | Groq credentials/model are missing or planner output is exhausted/invalid | Do not execute tools; emit a handled failed JSON report with the safe failure category and visible lifecycle events. |
| Unapproved fetch URL | URLFetch step URL is absent from the goal and all prior validated search results | Do not contact the URL; return a non-retryable `UNSAFE_URL` tool failure through ExecutionEngine and preserve it in the report. |
| Missing verified evidence | Evidence ledger is empty or contains only candidate/contradictory records | Do not call synthesis; return no findings and an explicit limitation with `failed` status. |
| Invalid final synthesis | Malformed JSON, extra source fields/URLs, or evidence IDs outside the verified ledger | Reject generated findings, preserve ledger-derived sources, record `SYNTHESIS_INVALID`, and return a partial report/limitation. |

## Hard bounds and action order

- Model operations retain the separate two-attempt limit. Planner waits for a valid numeric/HTTP-date `Retry-After` up to 60 seconds, defaults to 60 seconds for 429 or one second for other transient errors when the header is absent/invalid, and stops without retrying if the provider asks for more than 60 seconds. A malformed-plan repair also waits 60 seconds. Delays and attempts are visible in retry events; tests inject the sleeper. Exhausted rate limits produce category `rate_limit` with retryable cause and quota-reset guidance; terminal run status does not change that cause's classification. The report's `execution_summary.retries` counts tool retries; model attempts are recorded separately in events and the failure message.

- `MAX_RETRIES_PER_STEP = 2`; `MAX_TOOL_ATTEMPTS = 3` including the first call.
- `MAX_EXECUTION_STEPS = 20` tool calls per run. Fallback and revised replacement calls consume the same logical-step attempt budget.
- At most one validated plan revision per run; replan does not reset call/retry limits. Model output repair has its separate model-attempt limit and occurs before a plan is validated.
- One deterministic action is selected per failure: retry eligible transient errors; otherwise use an eligible prevalidated fallback; otherwise replan recoverable semantic/source failures if allowed; otherwise mark failed or enter terminal `FAILED` for invalid replan/configuration.
- Retry identical arguments. Never retry invalid arguments, unknown tools, invalid plans, security violations, authentication errors, or deterministic calculator failures.

## Demonstration injection

Failure injection is disabled by default and configured with:

```text
AGENT_INJECT_FAILURE=true
AGENT_FAILURE_MODE=tool_timeout
AGENT_FAILURE_TOOL=calculator
```

Supported modes are `tool_timeout` and `malformed_tool_response`; the optional tool is one of `web_search`, `url_fetch`, or `calculator`. The injector fires once on the first matching call, emits `FAILURE_INJECTED`, returns a normal failed `ToolResult`, and lets the same handler choose recovery. It never fabricates a successful result. Setting mode to `malformed_tool_response` creates a retryable `INVALID_RESPONSE` failure without exposing malformed bytes.

Expected event order for a recovered injected timeout:

```text
STEP_STARTED
TOOL_CALL_STARTED
FAILURE_INJECTED
TOOL_CALL_FAILED
RECOVERY_STARTED
RETRY_ATTEMPTED
RECOVERY_APPLIED
TOOL_CALL_STARTED
TOOL_CALL_SUCCEEDED
STEP_COMPLETED
```

If recovery fails, the final report must use `PARTIAL` or `FAILED` as appropriate, keep the failed step/failure, and state the cause and exhausted action in `limitations`. It must never claim the requested work succeeded.

## RCA: planner repair followed by Groq 429 (2026-09-23)

Run `51c63c98-ff92-4d14-ad94-fff9c7c08cc8` recorded `malformed structured planner output` at 23:26:04.590513Z and a scheduled repair at 23:26:04.593000Z. The final failure at 23:26:04.702766Z was `http_429_rate_limit_exceeded`. Thus the first response failed local validation and the second request was rate limited. The old repair path dispatched immediately; the transient-provider retry path also ignored Retry-After. The request sent the same plan schema both in the payload and again as an escaped JSON string. The controller discarded retryability and reported generic `llm_error`.

The specific request/token/daily quota and first validation defect cannot be recovered from these sanitized logs. Groq applies multiple organization-level quotas; account limits must be checked in its console. A synthetic request using the same schemas measured 12,256 user-message bytes before deduplication versus 8,055 after (34.3% reduction, not an exact token count).

D-041 removes the duplicate schema, paces both repair and transient retries, preserves the two-attempt cap, and gives actionable rate-limit failures. Daily quotas or an individual request exceeding an account limit can still prevent a live run; the program never fabricates a successful report or bypasses the provider's quota. See [Groq rate-limit headers](https://console.groq.com/docs/rate-limits).
# Planner validation diagnostics (D-042)

D-046: synthesis Groq failures retain their safe provider category and attempt
count instead of being labeled schema failures. Transient errors get at most
one retry, with provider delay capped at 60 seconds; longer delays stop locally.
Evidence stays in a partial report on exhaustion. Retry events are visible;
execution_summary.retries continues to count tool retries only.

## HTTPS adapter compatibility (D-045)

The Python 3.13 adapter used a removed `_check_hostname` attribute, causing
immediate unexpected fetch failures. Pass the TLS context instead. Bind the
public-IP connector after the stdlib constructor so it cannot be shadowed by
the default connector. Unexpected fetch failures include exception class only,
without raw response/exception content. Existing security/retry policy remains.

D-044: a syntactically valid but unsupported literal fetch URL fails planner
validation with `fetch_requires_search_result_reference`. Repair must supply an
explicit search-result reference and dependency; it must not guess another URL.
Unsupported literal fetch fallbacks produce `fallback_fetch_requires_goal_url`.
Both use the existing two-attempt budget. PlanValidator separately rejects
unproven literals before execution; executor authorization is retained.

D-043 filters argument-union diagnostics to the selected tool's schema. A URL
validation failure now reports `steps.1.input.url: value_error`, without search
or calculator branch errors. Search-result references are validated as plan
bindings, not URLs. Missing result indices fail in the executor before fetch
dispatch; unsafe resolved URLs still face the existing HTTPS/public-network
checks. The logged invalid URL's original value remains unknown.

When a response fails local validation, the bounded repair request receives
safe field paths and error codes (for example `steps.0.objective: missing`).
The retry trace and exhausted-attempt report preserve these diagnostics.
Never include raw values, arbitrary extra-field names, or custom exception
messages in public diagnostics. Goal mismatch and unregistered tool failures
use application-owned fixed codes. Validation remains strict and no tools run
until a plan passes validation. The original offending field in user run
`ded3b5de-cc71-4a7e-8a50-a703a71b3d94` is unknown because the previous version
discarded the diagnostics.

