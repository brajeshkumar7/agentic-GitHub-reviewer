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
| URL fetch failure | Timeout, HTTP status, unsafe redirect or unsupported content | Retry transient timeout/5xx; a safe alternate URL can be used only if declared and validated. Security failures are never retried or bypassed. |
| Calculator failure | Restricted expression/operation validation | Permanent for the same arguments; preserve failure and report the unavailable calculation. |
| LLM/API failure | Provider timeout/status/invalid response | Retry transient failures within the separate model-operation cap; authentication/configuration errors are terminal. Never log API keys. |
| Insufficient evidence | Evidence checks cannot verify or corroborate a claim | Search/fetch only within the plan, fallback and single replan limits; omit unsupported claims and explain the gap. |
| Execution step failure | Tool failure or dispatch/result validation failure | Route through `FailureHandler`, preserve step status and failure, skip dependent steps, and continue independent work. |
| Retry exhaustion | Two retries or global dispatch ceiling consumed | No further tool call. Mark the logical step failed and state the exhausted limit explicitly. |
| Invalid replan | Replanner returns malformed/unknown-tool/invalid-dependency plan | Revalidate through `PlanValidator`; a rejected revision makes lifecycle `FAILED`. |
| Configuration/security failure | Missing required setting, unsafe URL, invalid tool name/arguments | Do not retry or execute; return controlled terminal/step failure. |

## Hard bounds and action order

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
