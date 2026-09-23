# Failure Modes and Recovery

The agent must record failures and recovery actions in `tool_activity` and `recovered_failures`. It must never convert missing evidence into a confident finding.

| Failure | Detection | Recovery / result |
|---|---|---|
| Invalid or unsupported GitHub URL | URL parsing and host/path validation | Stop before network access; show a concise correction and return a CLI error. |
| Repository not found or inaccessible | GitHub 404/403 or missing metadata | Do not retry as transient; explain that only public repositories are supported and return `failed`. |
| Timeout or transient GitHub 5xx | Request exception or 5xx response | Retry a small bounded number of times with backoff; if still unavailable, return `partial` or `failed` with the failed step recorded. |
| GitHub rate limit | 403/429 and rate-limit headers | Respect reset/retry guidance where practical; avoid tight retry loops; return a clear partial/failed result if the limit persists. |
| Large repository/tree or source file | Configured file-count/size limits exceeded | Skip excess content deterministically, disclose coverage limits, and continue if enough evidence remains. |
| No usable Python files | Tree selection yields no supported source | Return a clear unsupported/limited result; do not imply Python analysis occurred. |
| Malformed Groq response or invalid report structure | Parse/schema validation fails | Make at most one bounded repair attempt using supplied evidence; otherwise emit a minimal valid error report or fail clearly. |
| Groq timeout, authentication, or quota error | Client exception/status | Do not expose credentials; retry only transient failures; if synthesis is unavailable, return deterministic findings with a clear unsynthesized limitation when possible. |
| AST parse error in a source file | Parser error with file and line | Record the file as skipped and continue with remaining files; do not execute it. |
| Failure injection for demonstration | Explicit demo option names a simulated failure point | Raise the selected synthetic failure once, route it through normal recovery, and record injection and outcome in the trace/report. |

## Recovery rules

- Retries are bounded and apply only to transient failures; invalid input, not-found responses, and authentication errors are not retried.
- Preserve successful evidence if a later step fails and label the report `partial` when it remains useful.
- Use `failed` when the repository cannot be identified or no meaningful review can be completed.
- Include skipped checks and remaining limitations in the final report.
