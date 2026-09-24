"""Groq OpenAI-compatible chat-completions adapter; never dispatches tools."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from research_agent.config import AgentSettings
from research_agent.models import LLMResponse
from research_agent.prompts import PLANNER_SYSTEM_PROMPT, RESEARCH_SUMMARY_SYSTEM_PROMPT

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_REQUEST_TIMEOUT_SECONDS = 30
MAX_GROQ_REQUEST_BYTES = 64_000
MAX_GROQ_RESPONSE_BYTES = 512_000
MAX_GROQ_COMPLETION_TOKENS = 2_048
_ALLOWED_OPERATIONS = {"plan_proposal", "plan_revision", "research_summary"}
_SYSTEM_PROMPTS = {
    "plan_proposal": PLANNER_SYSTEM_PROMPT,
    "plan_revision": PLANNER_SYSTEM_PROMPT,
    "research_summary": RESEARCH_SUMMARY_SYSTEM_PROMPT,
}


class GroqLLMError(RuntimeError):
    """Sanitized provider error; the message never includes request secrets."""

    def __init__(
        self, category: str, *, retryable: bool,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.category = category
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Groq request failed ({category})")


def _retry_after_seconds(value: str | None) -> float | None:
    """Parse only bounded header text; never expose provider response bodies."""
    if not value or len(value) > 128:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                return None
            seconds = max(0.0, (deadline - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


class GroqLLMClient:
    """Small stdlib transport adapter for Groq's fixed chat-completions API."""

    def __init__(self, settings: AgentSettings) -> None:
        self._settings = settings

    def generate(
        self, operation: str, payload: dict[str, Any], expected_schema: str
    ) -> LLMResponse:
        if operation not in _ALLOWED_OPERATIONS:
            raise GroqLLMError("unsupported_operation", retryable=False)
        key = self._settings.groq_api_key
        model = self._settings.groq_model
        if key is None or model is None:
            raise GroqLLMError("missing_configuration", retryable=False)

        try:
            schema = json.loads(expected_schema)
        except (ValueError, TypeError):
            raise GroqLLMError("invalid_expected_schema", retryable=False) from None
        request_payload = dict(payload)
        if request_payload.get("schema") == schema:
            request_payload.pop("schema", None)
        user_content = json.dumps(
            {
                "operation": operation,
                "payload": request_payload,
                "expected_schema": schema,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        request_body = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": _SYSTEM_PROMPTS[operation],
                },
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_completion_tokens": MAX_GROQ_COMPLETION_TOKENS,
        }
        # GPT-OSS uses reasoning tokens within the completion budget. Low effort
        # is sufficient for the constrained planning/synthesis tasks here and
        # avoids spending the full budget before producing the JSON response.
        if model in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
            request_body["reasoning_effort"] = "low"
        request_data = json.dumps(request_body).encode("utf-8")
        if len(request_data) > MAX_GROQ_REQUEST_BYTES:
            raise GroqLLMError("oversized_request", retryable=False)
        request = Request(
            GROQ_CHAT_COMPLETIONS_URL,
            data=request_data,
            headers={
                "Authorization": f"Bearer {key.get_secret_value()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "research-intelligence-agent/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=GROQ_REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read(MAX_GROQ_RESPONSE_BYTES + 1)
        except HTTPError as error:
            retryable = error.code == 429 or 500 <= error.code < 600
            retry_after = _retry_after_seconds(
                error.headers.get("Retry-After") if error.headers else None
            )
            provider_code: str | None = None
            try:
                error_payload = json.loads(error.read(16_384))
                raw_code = error_payload.get("error", {}).get("code")
                if isinstance(raw_code, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", raw_code):
                    provider_code = raw_code.lower()
            except (AttributeError, json.JSONDecodeError, TypeError, UnicodeDecodeError, OSError):
                pass
            finally:
                error.close()
            category = f"http_{error.code}"
            if provider_code is not None:
                category = f"{category}_{provider_code}"
            raise GroqLLMError(
                category, retryable=retryable, retry_after_seconds=retry_after
            ) from None
        except (TimeoutError, URLError, OSError):
            raise GroqLLMError("transport_error", retryable=True) from None

        if len(body) > MAX_GROQ_RESPONSE_BYTES:
            raise GroqLLMError("oversized_response", retryable=False)
        try:
            decoded = json.loads(body)
            content = decoded["choices"][0]["message"]["content"]
            request_id = decoded.get("id")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty model content")
            return LLMResponse(
                content=content,
                provider="groq",
                request_id=request_id if isinstance(request_id, str) else None,
            )
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError, ValidationError):
            raise GroqLLMError("invalid_provider_response", retryable=False) from None
