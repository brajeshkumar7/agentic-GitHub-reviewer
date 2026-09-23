# Architecture

## Components

- **CLI** parses a public GitHub URL and options, validates input, and presents the run trace and final output.
- **Planner/report synthesizer** uses Groq through an environment-configured client. It produces a concise action plan and summarizes evidence already gathered; it does not decide whether tool output is true.
- **GitHub client** retrieves public repository metadata, the recursive file tree, and selected Python files through GitHub's REST API.
- **Python analyzer** applies deterministic AST-based checks to downloaded source in memory. It never imports or executes target code.
- **Orchestrator** runs the plan, records tool outcomes, applies bounded retries where appropriate, and builds the final result.
- **Report renderer** emits the structured JSON contract and an optional readable Markdown view.

## Control flow

```mermaid
flowchart TD
    A[CLI: public GitHub URL] --> B[Validate and normalize input]
    B -->|invalid| Z[Explain error and exit]
    B --> C[Groq: create concise review plan]
    C --> D[Display plan before actions]
    D --> E[GitHub REST: metadata and file tree]
    E --> F[Select Python files within limits]
    F --> G[GitHub REST: fetch source files]
    G --> H[Python AST checks]
    H --> I[Groq: summarize evidence and limitations]
    I --> J[Validate report structure]
    J --> K[Render JSON / Markdown and tool trace]
    E -. error .-> R[Bounded retry / classify failure]
    G -. error .-> R
    C -. error .-> R
    I -. error .-> R
    R -->|recoverable| D
    R -->|unrecoverable| L[Partial or failed report]
    L --> K
```

## Data flow and boundaries

Only the normalized public repository identifier and retrieved public content flow into the review. Tool results are retained with provenance so findings can cite repository paths and line numbers. The model receives bounded evidence for synthesis; deterministic analysis remains the source of code observations. The orchestrator records concise action summaries, not private model reasoning.

The report follows the contract in `PROJECT_SPEC.md`. Network clients, the Groq client, and the analyzer should be separable so tests can replace them with fakes.

## External interfaces

- **Input:** public GitHub URL plus optional output/failure-demo flags.
- **GitHub:** unauthenticated public REST API requests for repository metadata, tree, and raw file contents; honor response errors and rate-limit information.
- **Groq:** API key and model supplied through environment variables; keep model selection out of source code.
- **Output:** JSON report to standard output or a requested file, with progress and plan on standard error or another clearly separated channel.
