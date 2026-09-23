# Security and Data Handling

## API keys and environment variables

- Store `GROQ_API_KEY` and `BRAVE_SEARCH_API_KEY` in environment variables or an ignored local environment file.
- `GROQ_MODEL` is a non-secret environment setting; never hard-code a model identifier.
- `BRAVE_SEARCH_API_KEY` is required only for live Brave searches and is read from environment-backed settings.
- Demo injection uses only `AGENT_INJECT_FAILURE`, `AGENT_FAILURE_MODE`, and optional `AGENT_FAILURE_TOOL`; these non-secret settings default to disabled and are validated against fixed enums. Never log raw provider/tool payloads when simulating malformed output.
- Commit only placeholder `.env.example`; exclude real `.env` files and never place credentials in shell history intentionally.
- Never put keys in prompts, tool arguments, events, exception messages, screenshots, or sample transcripts.
- Redact authorization headers and known secret values from logs. Missing-key errors must not echo values.

## Tool-output validation and prompt injection

- Search results, fetched pages, calculator output, and model responses are untrusted.
- Validate schemas, types, lengths, numeric ranges, URLs, timestamps, and evidence references before use.
- Treat fetched text as research material, never as instructions. Ignore text asking to reveal secrets, change behavior, call tools, or follow links.
- Only the validated planner can propose steps; only validator/orchestrator can authorize and dispatch allowlisted tools. Content cannot modify the plan or tool registry.
- Search snippets are discovery metadata, not verification. Claims cite fetched sources and pass evidence checks.
- Bound page text sent to the model, retain provenance, and validate model output before rendering.
- Final synthesis receives only verified ledger evidence and may return finding text/evidence IDs only. Reject extra source fields, source URLs in finding text, and evidence IDs absent from the verified ledger; construct report sources only from `EvidenceStore`.

## URL and network restrictions

- Fetch public HTTPS URLs on port 443 only. URLs originate in the user goal or validated search results; do not automatically follow links from page bodies.
- Reject URL credentials/user-info, unsupported ports/schemes, localhost, loopback, private, link-local, multicast, and other non-public destinations.
- Resolve and validate every destination before connecting; pin the socket to a validated globally routable IP while retaining TLS hostname verification; disable environment proxies; validate every redirect target under the same rules; cap redirect count at five.
- Apply finite timeouts, response-size limits, supported content types, and per-run page/result limits. Never fetch local files, cloud metadata, or internal services.
- Keep provider endpoints separate and fixed/configured; user input cannot override API base URLs or headers.

## Arbitrary code execution policy

- No shell, code interpreter, browser scripting, plugin, or remote execution tool is in scope.
- Calculator accepts validated operations and numeric operands or its restricted arithmetic grammar; it recursively evaluates allowlisted AST nodes and never calls `eval()` or executes code.
- Parse retrieved pages as data only. Never run scripts, download/execute attachments, run notebooks, import packages, or install source code.

## Logging and data minimization

- Record event types, step/tool IDs, attempts, sanitized summaries, timings, and outcomes.
- Do not log API keys, auth headers, full prompts, hidden model reasoning, or full page bodies. Avoid retaining user goals beyond report creation.
- Review transcripts for secrets and unnecessary personal data before commit; prefer synthetic/fake responses.
- Reports may contain public URLs and short descriptions. Disclose that fetched public source text is sent to configured Groq for synthesis; do not submit private data or secrets as research content.

## Limitations

This is a research assistant, not a source-authenticity oracle or guarantee of comprehensive coverage. Web data may be incomplete, manipulated, unavailable, or misdated. Disclose uncertainty, conflicts, and evidence gaps; never present unsupported claims as verified.
