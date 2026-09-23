# Project Specification: Autonomous Research Intelligence Agent

## Purpose

Build a Python CLI agent that accepts a natural-language research goal, creates and validates an executable plan, runs it through approved tools, recovers from bounded failures, and returns a structured research brief with traceable evidence. The initial use case is researching recent developments in a topic, verifying candidates with reliable sources, comparing them, and summarizing the results.

## Functional requirements

1. Accept one non-empty natural-language goal per run. Resolve relative time windows against a UTC run-start timestamp. If none is given, default to the preceding seven days and disclose that default.
2. Use the configured Groq model to propose a concise structured plan before any research tool is called.
3. Validate before execution: 1–8 uniquely identified steps, known tool names, schema-valid arguments, valid acyclic dependencies, and a success condition for every step. Planner-facing `PlanStep` fields are `id`, `objective`, `tool_name`, `input`, `expected_output`, `dependencies`, and `status` (`PENDING` on a new proposal); final report serialization uses the established report names. Reject or repair invalid output within retry limits.
4. Execute approved steps sequentially through the state machine in `ARCHITECTURE.md`. A dependent step starts only when prerequisites succeed or a validated recovery decision explicitly skips a dependency.
5. Provide three tools: web search, HTTPS page fetch, and deterministic calculator. A successful research run must use search and page fetch (two distinct tools); use calculator when the goal requires arithmetic. Search snippets alone are never verification evidence.
6. Verify each reported development using at least two independent fetched sources where available, preferring a primary source plus independent corroboration. If evidence is insufficient, report fewer than three developments or mark a candidate unverified; never invent support to fill a quota.
7. Select up to three developments within the requested window by relevance to goal, recency, evidence quality, and independent corroboration. Break ties by newer verified publication date, then greater independent-source count. Disclose selection limits.
8. Detect malformed, empty, contradictory, stale, oversized, or failed tool results; record the issue, attempt bounded recovery, and preserve valid evidence already collected.
9. Produce the JSON report below and a visible event trace without hidden model reasoning.
10. Provide deterministic one-shot failure injection for a sample run/test; it must use the normal executor and recovery path.

## Non-functional requirements

- Python 3.11+ CLI. This specification defines behavior, not application code.
- Tool, model, and report boundaries are validated and independently mockable.
- Use strict Pydantic v2 models for validated structured boundaries, as specified in `ARCHITECTURE.md`; forbid unknown fields and validate cross-field invariants.
- Hard limits: 8 plan steps; 20 total tool dispatches per run; 3 calls per logical tool step (initial call plus at most 2 retries, with every fallback/replanned replacement also consuming that same budget); 2 attempts per model operation (one retry); at most one validated-plan revision per run. A malformed structured response may use the model-operation retry before a valid plan exists. Limits are centralized in `research_agent.limits`.
- Apply finite connect/read timeouts and configured response, page, search-result, and token limits. Current tool bounds: search 8s/1 MB/10 results; fetch 10s/1 MB/20,000 extracted chars/five redirects; calculator 256 expression characters/64 AST nodes. LLM bounds are recorded in `DECISIONS.md`.
- Offline tests require no API keys, paid inference, or live network access.
- Reports cite evidence, identify uncertainty, distinguish verified facts from interpretation, and disclose skipped work.
- Logs and traces contain no API keys or private model reasoning.

## Input and output behavior

### Input

- Required: one natural-language goal as the CLI positional argument.
- Failure demonstration configuration is environment-only and disabled by default: `AGENT_INJECT_FAILURE=true`, `AGENT_FAILURE_MODE=tool_timeout|malformed_tool_response`, and optional `AGENT_FAILURE_TOOL=web_search|url_fetch|calculator`. One failure is injected per run and routed through ordinary recovery.
- Capture `run_started_at` once in UTC and use it for all relative date windows.
- Missing goal is a CLI usage error and causes no model/tool calls.

### Output

- Standard output: one valid JSON report on completion or handled failure.
- Standard error: concise plan, state/event summaries, and progress; no hidden reasoning or secret values.
- Exit code zero for `completed`, nonzero for `partial` or `failed`.

### Final report representations

The validated JSON report has exactly these top-level fields: `goal`, `status` (`completed`, `partial`, or `failed`), `plan`, `execution_summary`, `failures`, `recoveries`, `evidence`, `findings`, `limitations`, and `sources`.

- `plan`: ordered entries with `id`, `objective`, `tool_name`, `status`, and `dependencies`.
- `execution_summary`: `steps_total`, `steps_completed`, `steps_failed`, and `retries`.
- `evidence`: collected records with `evidence_id`, `goal_id`, producing `step_id`, `source_url`, `title`, publisher/source metadata, extracted `supporting_text`, and `retrieved_at`.
- `findings`: generated synthesis entries with a finding ID, title, summary, and one or more IDs of verified collected evidence.
- `sources`: deterministic projections of the evidence ledger. The synthesis model cannot return or add source records or URLs.

The Markdown representation contains `# Research Brief` and the sections `## Goal`, `## Plan`, `## Execution Summary`, `## Findings`, `## Evidence`, `## Failures and Recovery`, `## Limitations`, and `## Sources`. It labels findings as generated synthesis and evidence as observed collected information.

If verified evidence is missing, findings are omitted and the report explicitly states the evidence gap. A `completed` report requires at least one finding grounded in verified evidence. Use `partial` when useful evidence exists but planned work remains incomplete, and `failed` when no trustworthy findings can be produced.
## Tool contract

Tools accept validated JSON and return typed success or typed failure. They do not select subsequent tools or edit the plan.

### Web search

- Input: `query`, optional UTC date bounds, and bounded `max_results`.
- Output: ordered results `{title, url, snippet, source, published_at?}` and safe provider metadata. `source` is normalized to the result URL hostname.
- Results are untrusted discovery data, not evidence until fetched and checked.

### URL/page fetch

- Input: one HTTPS URL from the validated goal or search results.
- Output: `{final_url, title, publisher, published_at?, extracted_text, retrieved_at, truncated, status}`.
- Restrict to public HTTPS port 443 content per `SECURITY.md`; reject unsafe destinations, redirects, content types, or oversized pages. Never allow local-file or private-network access.

### Calculator

- Input: either an allowlisted operation (`add`, `subtract`, `multiply`, `divide`, `mean`, `percentage`) and numeric operands, or a restricted arithmetic expression.
- `add`, `subtract`, `multiply`, and `divide` require exactly two operands; `mean` requires at least one; `percentage` takes `[part, whole]` and returns `part / whole * 100`.
- Output: numeric result and operation metadata, or typed invalid-input/divide-by-zero failure. Reject non-finite operands and non-finite results.
- Expression grammar: decimal number literals, parentheses, unary `+/-`, and binary `+ - * /`; maximum 256 characters and 64 parsed AST nodes. Reject identifiers, function calls, attributes, powers, modulo, and all other syntax nodes.
- Use decimal-safe recursive parsing/evaluation; never call `eval()` or execute arbitrary code.

## Observable execution events

Emit ordered structured events: `run_started`, `plan_created`, `plan_rejected`/`plan_validated`, `step_started`, `tool_call_started`, `tool_call_succeeded`/`tool_call_failed`, `failure_injected`, `recovery_started`, `retry_attempted`, `recovery_applied`, `evidence_recorded`, `step_completed`/`step_skipped`, `report_validated`, `run_completed`.

Each event includes `run_id`, UTC timestamp, event type, optional `step_id`/`tool_name`, attempt number, outcome, duration when available, and sanitized summary. Never log auth headers, API keys, full prompts, or unbounded page content.

## Failure recovery

- Route every tool/execution failure through the state-machine recovery handler; no direct adapter retry loops.
- Allow at most 3 total calls per logical tool step (initial call plus up to 2 retries) and 20 total tool invocations per run including retries, fallbacks, and replanned replacements.
- Retry classified transient failures only, at most twice per logical step; respect provider retry timing only if it fits the run budget.
- Recovery order is deterministic: bounded transient retry; validated fallback for eligible semantic failures; at most one validated replan for remaining recoverable search/evidence failures; otherwise preserve the failure and continue independent work or terminate.
- Permit at most one validated-plan revision after the initial plan is accepted; a malformed structured model response may separately use its one bounded model-operation retry before a Plan exists. Every revised plan re-enters validation before execution.
- On unrecoverable failure, mark the step and dependents accurately, preserve valid evidence, produce `partial` or `failed`, and explain the limitation.
- See `FAILURE_MODES.md` for the full catalog.

## Explicitly out of scope

- Private/authenticated sources, account login, paywall bypass, and credentials for researched sites.
- Browser automation, email/social scraping, code execution, shell tools, and arbitrary plugins.
- Autonomous purchases, external writes, persistent memory, scheduled research, multi-user service, or UI beyond the CLI.
- Guaranteed discovery, legal/medical/financial advice, or claims of exhaustive verification.
- Additional tools or domains without an approved decision in `DECISIONS.md`.
