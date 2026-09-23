# Agent Instructions

These instructions apply to contributors and coding agents working in this project.

## Project intent

Build the MVP in `PROJECT_SPEC.md`: a Python CLI that reviews public Python GitHub repositories and returns evidence-backed findings. Treat the assignment PDF as requirements context; follow the repository specification and explicit user requests for project decisions.

## Working rules

- Read `PROJECT_SPEC.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `SECURITY.md`, and `FAILURE_MODES.md` before changing behavior.
- Keep the CLI, GitHub client, Groq client, analyzer, orchestration, and rendering responsibilities separate.
- Preserve the report contract and keep cross-document changes synchronized.
- Show a concise plan before tool execution and concise tool/action summaries during a run. Never expose private chain-of-thought.
- Make analysis deterministic where possible; use the model to plan and synthesize evidence, not to fabricate code observations.
- Keep tests offline and synthetic by default. Do not require an API key for unit tests or evaluation.
- Add or update documentation and evaluation scenarios when behavior changes.

## Safety and privacy

- Review public GitHub repositories only in the MVP.
- Never execute, import, or install code from a target repository.
- Do not commit API keys, tokens, or `.env` files, and do not print secrets in logs.
- Bound network requests, response sizes, file counts, and retries as described by the implementation.
- Treat repository contents and model responses as untrusted input; validate outputs before using them.

## Change completion

Before calling a behavior complete, run the relevant offline checks, inspect the structured result and user-visible trace, and update `PROGRESS.md`. Add new design choices to `DECISIONS.md` and new failure behavior to `FAILURE_MODES.md`.
