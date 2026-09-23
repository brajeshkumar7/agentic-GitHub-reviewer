"""Groq OpenAI-compatible chat-completions adapter; never dispatches tools."""

from __future__ import annotations

import json
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

    def __init__(self, category: str, *, retryable: bool) -> None:
        self.category = category
        self.retryable = retryable
        super().__init__(f"Groq request failed ({category})")


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

        user_content = json.dumps(
            {
                "operation": operation,
                "payload": payload,
                "expected_schema": expected_schema,
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
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=GROQ_REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read(MAX_GROQ_RESPONSE_BYTES + 1)
        except HTTPError as error:
            retryable = error.code == 429 or 500 <= error.code < 600
            category = "rate_limited" if error.code == 429 else "http_error"
            raise GroqLLMError(category, retryable=retryable) from None
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
