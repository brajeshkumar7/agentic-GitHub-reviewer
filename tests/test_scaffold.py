from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from research_agent.config import AgentSettings
from research_agent.models import (
    CalculatorInput,
    CalculatorOperation,
    Goal,
    Plan,
    PlanStep,
    StepStatus,
    ToolName,
    WebSearchInput,
)


COMPONENT_MODULES = (
    "research_agent.controller",
    "research_agent.planner",
    "research_agent.plan_validator",
    "research_agent.execution_engine",
    "research_agent.state",
    "research_agent.tools.registry",
    "research_agent.tools.web_search",
    "research_agent.tools.url_fetch",
    "research_agent.tools.calculator",
    "research_agent.failure_handler",
    "research_agent.evidence_store",
    "research_agent.event_logger",
    "research_agent.report_generator",
    "research_agent.llm_client",
)


def test_all_architecture_modules_import() -> None:
    for module_name in COMPONENT_MODULES:
        assert importlib.import_module(module_name)


def test_models_accept_valid_goal_plan_and_tool_arguments() -> None:
    now = datetime.now(timezone.utc)
    goal = Goal(text="Research recent RAG work", run_started_at=now)
    step = PlanStep(
        step_id="search-1",
        description="Find research sources",
        tool_name=ToolName.WEB_SEARCH,
        arguments=WebSearchInput(query="recent RAG research", max_results=5),
        depends_on=[],
        success_criteria="Return relevant public sources",
        status=StepStatus.PENDING,
    )
    plan = Plan(goal_id=goal.goal_id, steps=[step])

    assert plan.goal_id == goal.goal_id
    assert CalculatorInput(
        operation=CalculatorOperation.ADD, operands=[Decimal("1"), Decimal("2")]
    ).operands == [Decimal("1"), Decimal("2")]


def test_models_reject_invalid_goal_and_tool_contract() -> None:
    with pytest.raises(ValidationError):
        Goal(text="   ", run_started_at=datetime.now(timezone.utc))
    with pytest.raises(ValidationError):
        CalculatorInput(operation=CalculatorOperation.DIVIDE, operands=[1, 0])


def test_plan_rejects_unknown_dependency() -> None:
    now = datetime.now(timezone.utc)
    goal = Goal(text="Research", run_started_at=now)
    step = PlanStep(
        step_id="step-1",
        description="Search",
        tool_name=ToolName.WEB_SEARCH,
        arguments=WebSearchInput(query="topic", max_results=1),
        depends_on=["missing"],
        success_criteria="Found a source",
        status=StepStatus.PENDING,
    )
    with pytest.raises(ValidationError):
        Plan(goal_id=goal.goal_id, steps=[step])


def test_config_accepts_absent_or_complete_groq_credentials() -> None:
    assert AgentSettings.from_env({}).groq_api_key is None
    settings = AgentSettings.from_env(
        {"GROQ_API_KEY": "secret-token", "GROQ_MODEL": "model-name"}
    )
    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == "secret-token"
    assert "secret-token" not in repr(settings)
    assert "secret-token" not in str(settings.model_dump())


@pytest.mark.parametrize(
    "values",
    [
        {"GROQ_API_KEY": "only-key"},
        {"GROQ_MODEL": "only-model"},
        {"GROQ_API_KEY": "key", "GROQ_MODEL": "   "},
    ],
)
def test_config_rejects_incomplete_or_blank_credentials(values: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        AgentSettings.from_env(values)


def test_cli_help_and_controller_entrypoint(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_agent.cli import main

    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0
    assert "natural-language research goal" in capsys.readouterr().out

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("AGENT_INJECT_FAILURE", raising=False)
    monkeypatch.delenv("AGENT_FAILURE_MODE", raising=False)
    monkeypatch.delenv("AGENT_FAILURE_TOOL", raising=False)
    assert main(["Research RAG systems"]) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "failed"
    assert "[GOAL]" in captured.err
    assert "Scaffold only" not in captured.err


def test_cli_writes_jsonl_events_and_one_json_report(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from research_agent.cli import main

    for name in (
        "GROQ_API_KEY",
        "GROQ_MODEL",
        "AGENT_INJECT_FAILURE",
        "AGENT_FAILURE_MODE",
        "AGENT_FAILURE_TOOL",
    ):
        monkeypatch.delenv(name, raising=False)
    event_path = Path.cwd() / f".cli-events-{uuid4()}.jsonl"
    try:
        assert main(["Research RAG", "--events-jsonl", str(event_path)]) == 1
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
        assert report["status"] == "failed"
        assert events[0]["event_type"] == "GOAL_RECEIVED"
        assert events[-1]["event_type"] == "EXECUTION_COMPLETED"
        assert "[GOAL]" in captured.err
    finally:
        event_path.unlink(missing_ok=True)


def test_cli_rejects_missing_goal(capsys: pytest.CaptureFixture[str]) -> None:
    from research_agent.cli import main

    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == 2
    assert "required: goal" in capsys.readouterr().err


def test_package_entrypoint_starts() -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.pop("GROQ_API_KEY", None)
    environment.pop("GROQ_MODEL", None)
    environment["PYTHONPATH"] = str(project_root / "src")
    result = subprocess.run(
        [sys.executable, "-m", "research_agent", "--help"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "natural-language research goal" in result.stdout
