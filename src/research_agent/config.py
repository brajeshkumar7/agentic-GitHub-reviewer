"""Validated environment configuration with secret-safe representations."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ConfigDict, SecretStr, model_validator

from research_agent.models import FailureInjectionMode, StrictModel, ToolName


class AgentSettings(StrictModel):
    """Settings needed by later phases; no dotenv file is loaded implicitly."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, repr=False
    )

    groq_api_key: SecretStr | None = None
    groq_model: str | None = None
    brave_search_api_key: SecretStr | None = None
    agent_inject_failure: bool = False
    agent_failure_mode: FailureInjectionMode | None = None
    agent_failure_tool: ToolName | None = None

    @model_validator(mode="after")
    def validate_groq_pair(self) -> AgentSettings:
        if (self.groq_api_key is None) != (self.groq_model is None):
            raise ValueError("GROQ_API_KEY and GROQ_MODEL must be set together")
        if self.groq_model is not None and not self.groq_model.strip():
            raise ValueError("GROQ_MODEL must not be blank")
        if self.agent_inject_failure and self.agent_failure_mode is None:
            raise ValueError("AGENT_FAILURE_MODE is required when failure injection is enabled")
        return self

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AgentSettings:
        """Build settings from environment variables (or an injected mapping)."""

        if environ is None:
            import os

            environ = os.environ
        key = environ.get("GROQ_API_KEY", "").strip()
        model = environ.get("GROQ_MODEL", "").strip()
        brave_key = environ.get("BRAVE_SEARCH_API_KEY", "").strip()
        inject_text = environ.get("AGENT_INJECT_FAILURE", "false").strip().lower()
        if inject_text not in {"true", "false"}:
            raise ValueError("AGENT_INJECT_FAILURE must be true or false")
        mode_text = environ.get("AGENT_FAILURE_MODE", "").strip()
        tool_text = environ.get("AGENT_FAILURE_TOOL", "").strip()
        try:
            failure_mode = FailureInjectionMode(mode_text) if mode_text else None
            failure_tool = ToolName(tool_text) if tool_text else None
        except ValueError:
            raise ValueError("Failure injection mode or tool is unsupported") from None
        return cls(
            groq_api_key=SecretStr(key) if key else None,
            groq_model=model or None,
            brave_search_api_key=SecretStr(brave_key) if brave_key else None,
            agent_inject_failure=inject_text == "true",
            agent_failure_mode=failure_mode,
            agent_failure_tool=failure_tool,
        )
