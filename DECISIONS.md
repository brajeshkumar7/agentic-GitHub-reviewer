# Decisions

Record of the initial project choices. Add dated entries when a material decision changes.

| Decision | Choice | Reason |
|---|---|---|
| Initial interface | Python CLI | Small setup suitable for a take-home prototype and repeatable local runs. |
| Initial review scope | Public Python GitHub repositories | Python AST analysis gives the first version concrete, explainable checks without broad language claims. |
| Planning and synthesis | Groq API, configured through environment variables | Uses the provider selected for this project; model selection remains configurable. |
| Repository retrieval | GitHub public REST API | Retrieves repository metadata, tree information, and source without cloning or executing project code. |
| Second analysis tool | Local Python AST analyzer | Provides deterministic source checks and line-based evidence distinct from API retrieval. |
| User-visible reasoning | Concise plan and action summaries | Makes planning and tool use legible without exposing private model reasoning. |
| Output | Structured JSON, with optional Markdown presentation | Gives downstream code a stable result while keeping reports readable. |
| Offline evaluation | Synthetic fixtures and mocked external clients | Makes tests reproducible without network access, API keys, or inference charges. |
| Failure demonstration | Deterministic injected tool failure | Ensures the recovery path can be shown reliably in sample runs. |

## Configuration

Keep the Groq API key and model name in environment configuration. Do not hard-code a model identifier into application logic. Groq documents an OpenAI-compatible API endpoint; follow its [compatibility documentation](https://console.groq.com/docs/openai) for the endpoint and request shape, and recheck provider documentation when implementing or upgrading the client.
