# Failure Modes and Recovery Contract

All failures are observable, classified by the orchestrator, and bounded by `PROJECT_SPEC.md`. Adapters return typed failures; they do not retry or dispatch other tools themselves.

| Failure mode | Detection | Allowed response | Terminal/report behavior |
|---|---|---|---|
| Tool timeout | Connect/read deadline exceeded | Retry once if transient and budget remains | Record attempts; exhaustion fails step, skips blocked dependents, and allows only independent work. |
| Search API failure | Brave timeout, 401/403, 429, 5xx, oversized body, or malformed JSON/results | Normalize to a typed failure; only transient timeout/429/5xx are retryable by the future engine | Never expose the subscription token or raw API body; invalid responses provide no candidates. |
| Unknown or unregistered tool | Registry lookup or fixed-name validation fails | Reject lookup; dispatch returns a sanitized `INVALID_ARGUMENT` `ToolResult` where call identity is available | No tool is dispatched; the model cannot add registry entries. |
| Invalid tool response | Schema/type validation fails, field missing, or value out of range | One retry for transient/provider anomaly; never accept malformed data as evidence | Record validation error; persistent failure loses that evidence and is disclosed. |
| Malformed planner output | Invalid JSON/schema, missing fields, unknown tool, cycles, mismatched arguments, unsafe args, wrong goal ID, or >8 steps | One prompt-template repair attempt, then full Pydantic and plan validation again; malformed raw content is bounded before reuse and never logged | Return a sanitized controlled planning failure after two model attempts; no tools can run before a valid plan. |
| Empty search results | Successful response has no candidates | One revised query/step through the single plan-repair allowance when useful | If still empty, return partial/failed with no fabricated developments. |
| URL fetch failure | HTTP error, unsafe destination, timeout, unsupported content, or no extractable text | Retry once only for transient errors; permanent/policy errors are not retried | Exclude page as evidence; continue with other sources; lower item count/status if verification fails. |
| Calculator failure | Unsupported expression node, invalid operation/operand, overflow, division by zero, oversized expression/AST | Typed non-retryable calculation failure; no input is executed | Mark dependent comparison unavailable and disclose omitted calculation. |
| LLM/API failure | Groq timeout, quota/rate limit, auth/config error, malformed response | Retry once only for transient errors; schema repair remains bounded by model/plan budgets | Never log key; use deterministic evidence only where contract permits, otherwise partial/failed. |
| Insufficient evidence | Fewer than two independent fetched sources, unverifiable date, contradiction, or weak support | Search/fetch more only within plan and invocation limits; do not lower the bar silently | Report fewer developments or mark unverified; state limitation. |
| Execution-step failure | Permanent tool error, missing prerequisite, malformed result, or executor invariant failure | Current execution baseline enters `RECOVERY`, retries one retryable failure once, otherwise marks the step failed | Preserve tool result/failure details; skip dependent steps, continue independent work, and hand partial state to synthesis. Fatal plan/precondition errors enter `FAILED` immediately. |
| Retry exhaustion | Per-step or run-wide budget consumed | No further attempt or nested retry | Record exhaustion and final state; never loop. |
| Unsafe/malicious page content | Prompt injection, unsafe links, malformed content | Treat as data; ignore instructions; validate content; do not follow embedded links automatically | Record a limitation if blocked content affects evidence. |
| Report validation failure | Missing field, invalid status/time, dangling evidence ID | One bounded repair using validated evidence ledger | If still invalid, emit minimal valid failure report or explicit process error; never emit invalid success. |
| Injected failure | Demo option names allowlisted tool and failure mode | Inject once at adapter boundary and route through normal recovery | Include injection/recovery in events/report; disabled unless explicitly selected. |

## Global recovery rules

- Maximum 2 total attempts per tool step, including initial attempt; 20 tool invocations per run including retries.
- Maximum 2 attempts for each model operation (one retry). A malformed planner response may be corrected once before a validated plan exists; this does not change a validated plan revision. Maximum plan length is 8; execution dispatch ceiling is 20 calls total, including retries/fallbacks; at most one validated-plan revision is allowed per run.
- Retry only timeouts, transient 5xx, or provider-declared temporary throttles; respect retry timing only when it fits the budget.
- The current engine implements only the single bounded retry above and deterministic failed-step/dependency handling. Fallback selection, runtime replanning, and injected failures remain deferred per D-030.
- Never retry invalid input, unsafe destinations, permanent not-found/authorization errors, or deterministic calculator errors without a validated repair.
- Every recovery action is an explicit transition from `RECOVERING`; every failure/retry is a structured event.
- Preserve valid evidence; mark partial work honestly. Never fill gaps with unsupported model-generated claims.
