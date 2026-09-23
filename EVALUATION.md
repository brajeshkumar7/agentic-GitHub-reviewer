# Evaluation Plan

Evaluation must be repeatable offline using synthetic repositories and fake GitHub/Groq clients. No test should need a paid inference call or live network access.

## Synthetic fixtures

Create small Python repository fixtures with controlled examples: a clean module, a module triggering selected AST checks, a syntax-invalid file, a repository with no Python source, and a tree that exceeds configured limits. Keep each fixture minimal and document the expected observations.

## Required scenarios

| Scenario | Setup | Expected result |
|---|---|---|
| Successful review | Valid public-style URL; fake metadata/tree/source; fake valid Groq responses | Visible plan precedes tools; GitHub and AST tools run; report is structurally valid and evidence cites correct fixture paths/lines. |
| Invalid URL | Unsupported host, malformed path, or non-repository URL | Rejected before network calls; concise actionable error. |
| Repository unavailable | Fake GitHub 404/403 | No transient retry; clear failed result and public-only limitation. |
| Transient GitHub error | Fake timeout/5xx followed by success | Bounded retry occurs; review completes and recovery is recorded. |
| Persistent API/rate-limit error | Fake repeated timeout or 429/403 limit | Retry budget is bounded; result is partial/failed with no misleading findings. |
| Malformed model output | Fake invalid JSON or missing required fields | Validation catches it; bounded repair path runs or a clear valid failure/partial result is returned. |
| AST parse failure | Fixture includes syntactically invalid Python | File is skipped and disclosed; valid files are still reviewed. |
| Injected failure | Enable deterministic failure at a documented tool boundary | Normal recovery executes; trace and report show the injected failure and outcome. |
| Offline evaluation | Replace all external clients with fakes | Full evaluation runs without network access or environment credentials. |

## Quality checks

- Confirm every finding has repository-relative evidence and a line or line range when available.
- Confirm tool activity is ordered, concise, and contains no secret values or private model reasoning.
- Confirm report status matches completed, partial, or failed work.
- Confirm the Markdown view, if implemented, represents the same findings and limitations as JSON.
- Manually review two or three sample transcripts against the assignment requirement to show planning, tool calls, failure handling, and final output.
