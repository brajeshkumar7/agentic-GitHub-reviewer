"""Validated environment configuration with secret-safe representations."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ConfigDict, SecretStr, model_validator

from research_agent.models import StrictModel


class AgentSettings(StrictModel):
    """Settings needed by later phases; no dotenv file is loaded implicitly."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, repr=False
    )

    groq_api_key: SecretStr | None = None
    groq_model: str | None = None

    @model_validator(mode="after")
    def validate_groq_pair(self) -> AgentSettings:
        if (self.groq_api_key is None) != (self.groq_model is None):
            raise ValueError("GROQ_API_KEY and GROQ_MODEL must be set together")
        if self.groq_model is not None and not self.groq_model.strip():
            raise ValueError("GROQ_MODEL must not be blank")
        return self

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AgentSettings:
        """Build settings from environment variables (or an injected mapping)."""

        if environ is None:
            import os

            environ = os.environ
        key = environ.get("GROQ_API_KEY", "").strip()
        model = environ.get("GROQ_MODEL", "").strip()
        return cls(
            groq_api_key=SecretStr(key) if key else None,
            groq_model=model or None,
        )
