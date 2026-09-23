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
| D-010 | Hard bounds: max 8 plan steps; 2 total calls per step (initial plus one retry or fallback); 20 tool calls/run; 2 attempts/model operation; one plan revision/run. A revision is either invalid-plan repair or runtime replan, not both; no revision resets budgets. | Preserves current specification limits and prevents loops. |
| D-011 | Recovery priority: transient retry; otherwise eligible validated fallback; then one validated plan revision for unresolved work; otherwise fail step and continue partial only where useful. | Provides deterministic choice among recovery options while preserving evidence and budgets. A fallback consumes the step's second call. |
| D-012 | Run-local in-memory state and evidence; no persistence in v1. | Sufficient for one CLI invocation and avoids unrequested storage behavior. |
| D-013 | Visible trace whitelist: goal, structured plan, statuses, tool calls/outcomes, failure/recovery events, final result only. | Demonstrates planning and orchestration without exposing hidden chain-of-thought or sensitive payloads. |
| D-014 | Search snippets are discovery only; reported developments target two independent fetched sources and prefer primary-source corroboration. | Claims must be grounded in accessible source material; evidence gaps stay explicit. |
| D-015 | Default relative time window is seven days from one UTC run-start timestamp. | Keeps “latest” stable and testable. |
| D-016 | Synthetic fixtures and fake clients are the default test strategy; deterministic one-shot failure injection exercises normal recovery. | No keys, paid inference, or external API access are needed in standard evaluation. |

## Open decisions before tool-adapter implementation

- **Search provider/API:** select a provider and confirm student/free access, key setup, request/response shape, and rate limits. Keep `WebSearchTool` provider-neutral until selected.
- **Resource limits:** set concrete connect/read timeouts, max response/page bytes, max search results/pages, and model input/output token limits. Call/step/retry counts are already fixed above.
- **Source reliability operations:** decide the practical rule for classifying primary publishers, independent secondary sources, and source-group independence. Search ranking alone cannot establish reliability.
- **Exact dependency/version lock:** pin the validation library and provider SDK versions during project scaffolding; this phase chooses Pydantic v2 as the schema approach but installs nothing.

## Configuration reference

- `GROQ_API_KEY`: secret required for live model calls; never committed or logged.
- `GROQ_MODEL`: non-secret model identifier for live calls; environment-configured.
- Search provider name/key: record after provider selection; key is environment-only.
- API compatibility details for Groq should be checked against its [official documentation](https://console.groq.com/docs/openai) when its client is implemented.
