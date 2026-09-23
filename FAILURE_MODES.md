# Failure Modes and Recovery Contract

All failures are observable, classified by the orchestrator, and bounded by `PROJECT_SPEC.md`. Adapters return typed failures; they do not retry or dispatch other tools themselves.

| Failure mode | Detection | Allowed response | Terminal/report behavior |
|---|---|---|---|
| Tool timeout | Connect/read deadline exceeded | Retry once if transient and budget remains | Record attempts; exhaustion fails step, skips blocked dependents, and allows only independent work. |
| Invalid tool response | Schema/type validation fails, field missing, or value out of range | One retry for transient/provider anomaly; never accept malformed data as evidence | Record validation error; persistent failure loses that evidence and is disclosed. |
| Malformed planner output | Invalid schema/JSON, unknown tool, cycles, unsafe args, or >8 steps | One planner repair, then full validation again | No tools before valid plan; exhaustion returns `failed`. |
| Empty search results | Successful response has no candidates | One revised query/step through the single plan-repair allowance when useful | If still empty, return partial/failed with no fabricated developments. |
| URL fetch failure | HTTP error, unsafe destination, timeout, unsupported content, or no extractable text | Retry once only for transient errors; permanent/policy errors are not retried | Exclude page as evidence; continue with other sources; lower item count/status if verification fails. |
| Calculator failure | Invalid operation/operand, overflow, or divide by zero | Repair input only if validated and within plan-repair budget | Mark dependent comparison unavailable and disclose omitted calculation. |
| LLM/API failure | Groq timeout, quota/rate limit, auth/config error, malformed response | Retry once only for transient errors; schema repair remains bounded by model/plan budgets | Never log key; use deterministic evidence only where contract permits, otherwise partial/failed. |
| Insufficient evidence | Fewer than two independent fetched sources, unverifiable date, contradiction, or weak support | Search/fetch more only within plan and invocation limits; do not lower the bar silently | Report fewer developments or mark unverified; state limitation. |
| Execution-step failure | Permanent tool error, missing prerequisite, or executor invariant failure | Enter `RECOVERING`; retry/repair only within budget | Mark step `FAILED`, dependents `SKIPPED`; preserve prior evidence and produce partial/failed report. |
| Retry exhaustion | Per-step or run-wide budget consumed | No further attempt or nested retry | Record exhaustion and final state; never loop. |
| Unsafe/malicious page content | Prompt injection, unsafe links, malformed content | Treat as data; ignore instructions; validate content; do not follow embedded links automatically | Record a limitation if blocked content affects evidence. |
| Report validation failure | Missing field, invalid status/time, dangling evidence ID | One bounded repair using validated evidence ledger | If still invalid, emit minimal valid failure report or explicit process error; never emit invalid success. |
| Injected failure | Demo option names allowlisted tool and failure mode | Inject once at adapter boundary and route through normal recovery | Include injection/recovery in events/report; disabled unless explicitly selected. |

## Global recovery rules

- Maximum 2 total attempts per tool step, including initial attempt; 20 tool invocations per run including retries.
- Maximum 2 attempts for each model operation; at most one plan repair/replan per run.
- Retry only timeouts, transient 5xx, or provider-declared temporary throttles; respect retry timing only when it fits the budget.
- Never retry invalid input, unsafe destinations, permanent not-found/authorization errors, or deterministic calculator errors without a validated repair.
- Every recovery action is an explicit transition from `RECOVERING`; every failure/retry is a structured event.
- Preserve valid evidence; mark partial work honestly. Never fill gaps with unsupported model-generated claims.
