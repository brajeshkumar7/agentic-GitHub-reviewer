# Security and Privacy

## Scope and trust boundaries

The MVP accepts public GitHub repositories only. Repository files, metadata, and model responses are untrusted input. The project offers code-quality observations, not a security audit or guarantee that a repository is safe.

## Required controls

- Store `GROQ_API_KEY` and other secrets in local environment configuration; provide an example file with placeholders only and keep real `.env` files out of version control.
- Never print API keys, authorization headers, or other credentials in errors, traces, sample transcripts, or reports.
- Never execute, import, install, or otherwise run downloaded repository code. Parse selected Python files as data only.
- Use HTTPS for external requests, validate the GitHub host and repository path, and avoid following arbitrary URLs found inside repository files.
- Bound request timeouts, retries, response/file sizes, and the number of files analyzed to limit resource use.
- Treat model output as untrusted: parse and validate it against the report contract, and ground findings in retrieved evidence.
- Keep logs and sample transcripts free of secrets and unnecessary personal data.

## Limitations

AST and heuristic checks can miss defects and can produce false positives. Do not claim comprehensive vulnerability detection. Reports must describe analysis coverage, skipped files, tool failures, and uncertainty. The agent does not modify repositories or submit findings to external services.
