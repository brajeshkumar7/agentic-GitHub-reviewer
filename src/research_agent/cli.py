"""Command-line scaffold. Agent execution is intentionally not implemented."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from research_agent.config import AgentSettings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-agent",
        description="Autonomous Research Intelligence Agent (scaffold)",
    )
    parser.add_argument("goal", nargs="?", help="natural-language research goal")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.goal is None:
        parser.print_usage(sys.stderr)
        print("research-agent: error: a research goal is required", file=sys.stderr)
        return 2
    try:
        AgentSettings.from_env()
    except ValidationError:
        print(
            "Configuration error: set GROQ_API_KEY and GROQ_MODEL together.",
            file=sys.stderr,
        )
        return 2
    print(
        "Scaffold only: research execution will be implemented in a later phase.",
        file=sys.stderr,
    )
    return 3
