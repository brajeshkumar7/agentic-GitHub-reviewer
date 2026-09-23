# Project Specification: Agentic GitHub Repository Reviewer

## Goal

Build a small Python CLI agent that accepts a public GitHub repository URL, plans a review, gathers repository data, performs Python-focused static checks, and returns an evidence-backed report. It is an internship take-home prototype intended to demonstrate planning, tool orchestration, recovery, and clear communication.

## MVP scope

- Accept one public GitHub repository URL per run.
- Validate and normalize the URL before making network requests.
- Display a concise, human-readable plan before acting. Show action and tool summaries as the run proceeds; do not expose private model reasoning.
- Use Groq for planning and report synthesis. Keep the API key and model selection in environment configuration.
- Use GitHub's public REST API to retrieve repository metadata, the file tree, and relevant Python source files.
- Analyze Python source without executing repository code. Initial checks should be deterministic and report verifiable evidence such as file paths and line numbers.
- Return a structured JSON result, with a readable Markdown rendering available as a CLI presentation.
- Recover from at least one deliberately induced tool failure and record the recovery in the result.

## Out of scope for the first version

- Private repositories, authenticated GitHub access, cloning, or running target code.
- Comprehensive vulnerability detection, semantic correctness claims, or guaranteed bug discovery.
- Non-Python language-specific analysis, persistent storage, a web UI, and automatic code changes.

## User interaction

The CLI takes a repository URL as its required argument. It may accept an output format and a failure-simulation option for demonstration. It prints the normalized target, proposed review steps, progress/tool summaries, and final status. Errors must be understandable and must not print secrets or raw credentials.

## Report contract

The JSON result contains:

- `status`: `completed`, `partial`, or `failed`.
- `repository`: canonical URL, owner/name, default branch when available, and detected primary language.
- `summary`: concise review overview.
- `findings`: list of `{id, category, severity, title, evidence, why_it_matters, suggested_fix, confidence}`. Each evidence item identifies a repository-relative path and line or line range when available.
- `tool_activity`: ordered summaries of tools called and their outcomes, without hidden reasoning or secrets.
- `recovered_failures`: failures, recovery action, and outcome.
- `limitations`: analysis coverage and any unavailable or skipped checks.

Malformed or unsupported repository content must not be presented as a successful full review. If there is not enough evidence to produce a finding, omit it rather than inventing one.

## MVP acceptance criteria

1. A valid public Python repository URL produces a visible plan, tool summaries, and a structured report.
2. At least two distinct tools are used: GitHub REST retrieval and local Python AST analysis.
3. Findings cite source evidence and distinguish observations from suggestions.
4. A deliberate failure is handled or reported gracefully and appears in `recovered_failures` or the failed/partial status.
5. Setup and run instructions, an architecture diagram, and two or three sample run transcripts are delivered with the implementation.
6. Synthetic tests cover successful analysis, invalid input, network/API failure, malformed model output, and injected failure recovery without paid inference or live network access.
