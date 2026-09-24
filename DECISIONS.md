# Architectural Decisions

This log records accepted architecture and unresolved implementation choices. Material changes require a new decision entry before implementation.

## Accepted project decisions

| ID | Decision | Rationale |
|---|---|---|
| D-001 | Domain: Autonomous Research Intelligence Agent for recent developments. | Exercises planning, live research, verification, comparison, and synthesis. |
| D-002 | Python 3.11+ CLI, one natural-language goal per run. | Python is assignment-compatible; CLI keeps setup small and demoable. |
| D-003 | Groq for planning/synthesis; `GROQ_API_KEY` and `GROQ_MODEL` come from environment. | Groq was selected earlier by the user; model remains configurable. |
| D-004 | Initial tool set: web search, HTTPS page fetch, deterministic calculator. Successful research uses search and fetch; calculator runs when arithmetic is relevant. | Meets the assignment's distinct-tool requirement and provides source verification and numerical comparison. |
| D-005 | One-process modular architecture with the named `AgentController`, `Planner`, `PlanValidator`, `ExecutionEngine`, `AgentState`, fixed `ToolRegistry`, three tools, `FailureHandler`, `EvidenceStore`, `EventLogger`, `ReportGenerator`, and `LLMClient`. No multi-agent or agent framework. | Matches the requested component set with direct ownership boundaries and minimal orchestration. |
| D-006 | Planner proposes; validator authorizes; engine owns state and calls; FailureHandler owns recovery policy; tools return data only. | LLM output cannot directly control arbitrary application behavior. |
| D-007 | Use strict Pydantic models for Goal/Plan/tool/evidence/event/failure/recovery/report boundaries; reject unknown fields and coercion. | Gives runtime validation and cross-field invariants without adopting a larger agent framework. |
| D-008 | Lifecycle: `RECEIVED`, `PLANNING`, `PLAN_VALIDATION`, `EXECUTING`, `RECOVERY`, `SYNTHESIZING`, then terminal `COMPLETED`, `PARTIAL`, or `FAILED`. | Makes normal and failure paths explicit; terminal outcomes communicate incomplete research. |
| D-009 | Sequential execution; ready steps follow declared plan order. Same validated plan/state/results/configuration yield the same execution and recovery policy. | Makes behavior auditable and deterministic without restricting model proposal text to be identical across runs. |
| D-010 | Hard bounds: max 8 plan steps; 2 total calls per step (initial plus one retry or fallback); 20 tool calls/run; 2 attempts/model operation; one validated-plan revision/run. A revision is a replan after an initial `Plan` has been validated; no revision resets budgets. | Preserves current specification limits and prevents loops. |
| D-011 | Recovery priority: transient retry; otherwise eligible validated fallback; then one validated plan revision for unresolved work; otherwise fail step and continue partial only where useful. | Provides deterministic choice among recovery options while preserving evidence and budgets. A fallback consumes the step's second call. |
| D-012 | Run-local in-memory state and evidence; no persistence in v1. | Sufficient for one CLI invocation and avoids unrequested storage behavior. |
| D-013 | Visible trace whitelist: goal, structured plan, statuses, tool calls/outcomes, failure/recovery events, final result only. | Demonstrates planning and orchestration without exposing hidden chain-of-thought or sensitive payloads. |
| D-014 | Search snippets are discovery only; reported developments target two independent fetched sources and prefer primary-source corroboration. | Claims must be grounded in accessible source material; evidence gaps stay explicit. |
| D-015 | Default relative time window is seven days from one UTC run-start timestamp. | Keeps “latest” stable and testable. |
| D-016 | Synthetic fixtures and fake clients are the default test strategy; deterministic one-shot failure injection exercises normal recovery. | No keys, paid inference, or external API access are needed in standard evaluation. |
| D-017 | Use a `src/research_agent/` package layout, PEP 621 `pyproject.toml` metadata, and a `research-agent` console script plus `python -m research_agent`. | Standard packaging keeps imports/install behavior explicit and provides both requested CLI entry paths. |
| D-018 | Use the strict Pydantic v2 models approved in `ARCHITECTURE.md` for the Phase 2 schema module and configuration; reject extra fields and invalid cross-field combinations. | Meets the existing validated-boundary contract using the already selected focused validation library. |
| D-019 | Use pytest as an optional development/test dependency; do not add a linter/formatter in this phase. | pytest is required for acceptance; no formatter is needed for this small scaffold and adding another tool is not justified yet. |
| D-020 | Define architecture component modules as protocol-only interfaces in Phase 2; CLI reports that runtime agent behavior is not implemented. | Establishes module boundaries while keeping planner, executor, LLM calls, and tools out of this phase. |
| D-021 | Keep configuration environment-only in Phase 2; `.env.example` is a blank template and no dotenv loader is added. Groq key/model must be configured together or both omitted for scaffold/offline use. | Avoids secret-bearing files and avoids another dependency; supports offline imports/tests without credentials. |
| D-022 | Implement Groq through an isolated stdlib `urllib` adapter using the fixed `https://api.groq.com/openai/v1/chat/completions` endpoint, JSON mode, no `tools` field, 30-second timeout, 64 KB request cap, 512 KB response cap, and 2,048 completion-token cap. | Keeps provider code isolated, avoids adding/installing an SDK, and makes model requests incapable of dispatching application tools. The endpoint and JSON mode follow the [Groq OpenAI compatibility](https://console.groq.com/docs/openai) and [chat-completions reference](https://console.groq.com/docs/api-reference). |
| D-023 | Planner-facing `PlanStep` uses `id`, `objective`, `tool_name`, `input`, `expected_output`, `dependencies`, and required `PENDING` status. Report serialization retains the Phase 1 field names through aliases. | Satisfies the Phase 3 planning contract without changing the established version-1 report shape. |
| D-024 | Centralize limits as 8 plan steps, 20 total execution/tool dispatches, one retry (two attempts) per model operation and per tool step, and one validated-plan replan allowance. | Makes the documented hard bounds reusable by schemas, planner, and the future execution engine. |
| D-025 | A malformed-output correction is the second attempt of the same model operation and occurs before any validated `Plan` exists; it is separate from the one validated-plan revision used for a later runtime replan. | Preserves the required malformed-output recovery while keeping runtime plan revisions capped at one and distinguishing output parsing from changing an accepted plan. |
| D-026 | Superseded by D-037: the initial implementation used Brave Web Search API behind `BraveSearchProvider` and `BRAVE_SEARCH_API_KEY`. | This records the original provider choice and why the repo previously required a paid search credential. |
| D-027 | Tool bounds: search timeout 8s, request timeout for pages 10s, max search results 10, max search query 600 chars/75 words, normalized search output 1 MB, page response 1 MB, extracted page text 20,000 chars, max five redirects, HTTPS port 443 only, and only globally routable destinations. | Gives predictable latency and memory bounds while reducing SSRF risk; redirect destinations are checked again before following. |
| D-028 | Calculator accepts either the existing allowlisted Decimal operations or a restricted expression containing decimal literals, parentheses, unary `+/-`, and binary `+ - * /`; no names, calls, attributes, powers, or other AST nodes. Limit expression length to 256 characters and AST nodes to 64. | Keeps the assignment's typed arithmetic operations while supporting a clearly bounded expression form without `eval`. |
| D-029 | Planner receives its available-tool catalog and Pydantic input/output schemas from the runtime `ToolRegistry`; `PlanValidator` must revalidate every step and fallback argument against that same registry before returning `ValidatedPlan`. The Planner remains proposal-only. | Removes duplicated/hard-coded tool availability, prevents plans from referencing omitted/unregistered tools, and keeps authorization in deterministic application logic. |
| D-030 | Implement the execution baseline as deterministic stable topological ordering, strict registry revalidation, typed result retention, ordered events, one retry for retryable failures, dependent-step skipping, and continuation of independent work. End ordinary execution in `SYNTHESIZING`; only report synthesis selects `COMPLETED`, `PARTIAL`, or `FAILED`. Fallback selection, replanning, and one-shot failure injection remain deferred to a later recovery phase. | Delivers safe execution without adding LLM control-flow calls or prematurely implementing the advanced `FailureHandler`; aligns the engine boundary with the lifecycle contract. |
| D-031 | Recovery follow-up supersedes the deferred portion of D-030: allow at most 2 retries (3 calls total) per logical step; route all failures through `FailureHandler`; permit a prevalidated fallback or one validated plan revision for eligible semantic failures; otherwise preserve a failed step and continue or fail the run. | Implements the recovery behavior explicitly requested for this development increment while retaining deterministic policy and hard bounds. |
| D-032 | Add environment-only, one-shot demo injection with `AGENT_INJECT_FAILURE`, `AGENT_FAILURE_MODE=tool_timeout|malformed_tool_response`, and optional allowlisted `AGENT_FAILURE_TOOL`. Injected errors are typed failures and use the ordinary recovery path. | Makes recovery demonstration repeatable offline without falsifying tool success or requiring live API access. |
| D-033 | Maintain the documented project phase numbering (Phase 6 evidence/report, Phase 7 evaluation/materials); record the user's “Phase 7 recovery” request as a recovery increment rather than marking either documentation phase complete. | The control plan's Phase 7 label differs from the request's use of Phase 7; this avoids claiming evidence/report or submission work is complete. |
| D-034 | Implement the user's Phase 8 evidence/report increment under the existing Phase 6 evidence/report scope. Adopt the requested report contract (`goal`, `status`, `plan`, `execution_summary`, `failures`, `recoveries`, `evidence`, `findings`, `limitations`, `sources`), with strict Pydantic validation and JSON/Markdown renderers. Findings are LLM-generated only from verified collected evidence IDs; sources are projected deterministically from the evidence ledger. | Implements the explicitly requested output structure while keeping source authority and report status in deterministic application logic; planner and execution behavior remain unchanged. |
| D-035 | Treat the user's Phase 9 request as a structured-observability increment appended after the existing Phase 8 final-audit gate; do not renumber earlier phases. Events use a stable execution ID, typed event type/status, UTC timestamp, optional step/tool identifiers, and redacted structured metadata. Provide an append-only JSONL logger and a renderer limited to plan/action/outcome/recovery summaries. | Preserves the approved phase history while adding the requested minimum event contract, persistent event format, and visible trace without exposing model reasoning or secrets. |
| D-036 | Complete the documented Phase 6 controller/CLI integration by composing the existing Planner, PlanValidator, ExecutionEngine, approved ToolRegistry, EvidenceStore, and ReportGenerator in one injectable `AgentController`. Resolve common relative/ISO date windows against one UTC start time; default to the prior seven days and disclose it. The CLI emits report JSON to stdout, trace events to stderr, and may write JSONL through `--events-jsonl`. ExecutionEngine permits fetch only for URLs present in the goal or an earlier validated search result. Successful page fetches become retrieval-verified evidence only; source quality ranking and claim-level corroboration remain disclosed limitations until their Phase 6 rules are implemented. | Makes the existing modules usable as one deterministic, mockable CLI workflow without adding tools or overstating evidence reliability. The optional log path is an output destination, not a new research input. |

| D-037 | Replace Brave Search with the `ddgs` Python package using its explicit `duckduckgo` text-search backend. Normalize DDGS results behind `WebSearchTool`; remove Brave key configuration and use bounded typed timeout, throttle, malformed-response, and provider failures. Map requested date windows to DDGS' supported day/week/month/year filters; these filters are discovery hints and fetched evidence dates remain authoritative. | User requested a search option without a paid Brave API key. DDGS exposes text search without a configured API credential; the upstream public backend can throttle or change, so all calls remain bounded and failures visible. Package reference: [DDGS on PyPI](https://pypi.org/project/ddgs/). |
| D-038 | For Groq GPT-OSS 20B/120B requests, explicitly set `reasoning_effort=low` and include lowercase `json` in the planner's JSON-mode instruction. Leave other configured models on their provider defaults. | A direct GPT-OSS JSON-mode probe succeeded with low reasoning effort, while the app's planner failed before tool execution. This aligns the app request with the demonstrated successful configuration without changing model selection or execution policy. |
| D-039 | Preserve only sanitized Groq HTTP status and provider error-code identifiers in planner failure reports; never include raw response bodies. | The CLI previously reduced all provider failures to `PlannerProviderError`, preventing diagnosis. Status/code identifiers are sufficient to guide troubleshooting without logging prompts, response text, or secrets. |
| D-040 | Send an explicit `User-Agent: research-intelligence-agent/0.1` header on Groq requests. | The same minimal request returned 403 from Python urllib without an explicit User-Agent and succeeded when this header was added. This aligns the provider adapter with the verified request while retaining the fixed endpoint and secret-safe headers. |

## D-041 — Accepted Groq rate-limit correction

Send the output schema once as a JSON object, removing an identical copy in the payload. Preserve numeric/date `Retry-After` as validated seconds. Planner owns the existing two-attempt budget and injected sleep: wait the requested delay up to 60 seconds; on 429 without a usable header wait 60 seconds; on other transient errors without a header wait one second. If the requested delay exceeds 60 seconds, stop without retrying early. Pace malformed-plan repair by 60 seconds too, because its first response consumed quota. Report rate limits with their correct category and retryability, attempts, and quota guidance. No adapter retry loop or account-limit bypass. This is a correction to the existing CLI integration; phase gates remain unchanged.

## Open decisions before full evidence verification and report integration

- **Source reliability operations:** decide the practical rule for classifying primary publishers, independent secondary sources, and source-group independence. Search ranking alone cannot establish reliability.
- **Exact dependency/version lock:** pin the validation library and DDGS versions during final packaging; Groq and page retrieval continue to use stdlib networking.

## Configuration reference

- `GROQ_API_KEY`: secret required for live model calls; never committed or logged.
- `GROQ_MODEL`: non-secret model identifier for live calls; environment-configured.
- DDGS web search requires no API credential. Search provider and tool resource bounds are set in D-027 and D-037. Source reliability operations remain open for a later evidence phase. Groq request timeout and response-size bounds are set in D-022.

# D-042 — Safe planner validation feedback

The user's run `ded3b5de-cc71-4a7e-8a50-a703a71b3d94` ended in local
structured-output validation failure after two attempts. Its report does not
retain the underlying validation cause; a specific invalid field cannot be
established retrospectively. The planner discarded validation details and its
repair prompt lacked specific corrective feedback.

Keep strict schemas and the existing two-attempt/60-second pacing policy.
Supply bounded schema field paths and validation codes to repair requests,
retry events, and final failure reports. Exclude input values, unknown field
names, and custom validator messages from diagnostics. Explicitly describe the
Plan shape, exact goal ID, pending status, tool arguments, and reporting boundary
in the planner prompt. No schema relaxation, fabricated plan, new tools, or live
API calls. Offline regression suite: 104 passed.

# D-043 — Bind fetch plans to discovered search results

The live validation trace shows an invalid fetch URL and unrelated union-branch
errors. Its raw value is unknown. Inspection confirms there is no supported
plan-time reference to URLs that search has yet to discover. Add a plan-only
`SearchResultReference` with `search_step_id` and zero-based `result_index`.
It is permitted only for URL-fetch steps with a direct search dependency.
The executor resolves it from a successful validated result before constructing
a concrete URLFetchInput and applying all existing authorization/network checks.
Missing results fail without dispatch. ToolCall and tool schemas remain concrete;
fallbacks remain concrete. No interpolation, expressions, or arbitrary paths.
Filter union validation diagnostics to the selected tool's input branch.

# D-044 — Validate fetch provenance before execution

Run `fff43870-7e63-4802-a195-1f3346f21cf3` passed planning but its
fetch URL was absent from the goal and search results. D-043 supported references
but still accepted unsupported literal URLs. Planner now rejects literals not
supplied in the goal with `fetch_requires_search_result_reference`, routing them
through the existing bounded repair. Fetch fallbacks require a goal URL.
PlanValidator independently rejects literal primary/fallback URLs absent from
the goal and already collected search results. Executor authorization remains
unchanged. No guessed URLs are silently converted to a different source.

# D-045 — Python 3.13 HTTPS transport compatibility and DNS pinning

Local stdlib inspection confirms HTTPSHandler no longer retains
`_check_hostname` on Python 3.13. Our handler accessed it before sending the
request, producing AttributeError hidden by generic failure normalization.
Pass the existing TLS context without that obsolete attribute.
HTTPConnection.__init__ also assigns `_create_connection` on the instance,
shadowing our subclass method. Bind the validated public-IP connector after
base initialization. Preserve TLS hostname verification and all URL checks.
Unexpected failures expose only the exception class, never exception content.
Offline transport tests now cover the actual adapter boundary instead of only
injected page transports. No live network calls made.

# D-046 — Preserve synthesis provider failures and bounded retries

The user's run `a8047423-6716-4024-8019-4fac4e1b1b1e` completed search and
both fetches but synthesis raised GroqLLMError. The old report discarded its
category, so the specific provider cause is unknown. Separate provider failures
from invalid synthesis output; preserve safe category and attempt count, with
rate-limit classification where applicable. Retry transient provider failures
within the existing two-model-attempt limit, honoring Retry-After up to 60s,
defaulting to 60s for 429 and 1s for other transient failures. Emit visible retry
events. Preserve collected evidence on exhaustion. No live API calls were made.

