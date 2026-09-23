# Implementation Plan

Build the smallest end-to-end vertical slice first, then harden its boundaries and demonstrate the assignment requirements.

## 1. Project foundation

- Add Python 3.11+ project metadata, dependency and development setup, environment example, and a clear README.
- Define the report types and CLI contract from `PROJECT_SPEC.md` before implementing orchestration.
- Keep clients and analyzers independently replaceable for offline tests.

## 2. Input and retrieval

- Implement CLI parsing and strict validation for public GitHub repository URLs.
- Retrieve metadata and the recursive tree through GitHub REST; select a bounded set of Python files and fetch their content.
- Handle missing repositories, unsupported/private access, oversized trees/files, rate limits, timeouts, and API errors without exposing credentials.

## 3. Planning and analysis

- Add an environment-configured Groq client and prompt it for a short, user-visible action plan.
- Implement deterministic Python AST checks that produce findings with repository-relative evidence and line numbers.
- Keep analysis bounded; never execute or import target repository code.

## 4. Orchestration and recovery

- Execute retrieval and analysis steps in order, recording concise tool activity.
- Add bounded retries for transient failures and explicit handling for malformed model output.
- Add a deterministic failure-injection option for the demo and return `partial` or `failed` when recovery cannot complete.
- Validate the final report against the declared contract before rendering it.

## 5. Evaluation and assignment deliverables

- Add synthetic Python repository fixtures and offline tests using fake GitHub and Groq clients.
- Cover successful review, invalid URL, API timeout/rate limit, malformed synthesis, and injected failure.
- Write two or three sample run transcripts showing plans, tool calls, recovery, and final results.
- Complete the architecture diagram and a one-page design/limitations/future-work write-up, linked from the README.

## Completion gate

The project is ready to present when a new user can follow the README, run an online review with their own Groq key, run the offline evaluation without a key or network, inspect the visible plan/tool trace, and reproduce the deliberate failure demo.
