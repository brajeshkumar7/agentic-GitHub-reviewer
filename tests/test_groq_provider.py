from __future__ import annotations

import json
from typing import Any

import pytest

from research_agent.config import AgentSettings
from research_agent.providers import groq
from research_agent.providers.groq import GroqLLMClient, GroqLLMError


class FakeHTTPResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


def test_groq_adapter_uses_fixed_endpoint_json_mode_and_no_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> FakeHTTPResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeHTTPResponse(
            json.dumps(
                {"id": "req-1", "choices": [{"message": {"content": '{"ok":true}'}}]}
            ).encode()
        )

    monkeypatch.setattr(groq, "urlopen", fake_urlopen)
    settings = AgentSettings.from_env(
        {"GROQ_API_KEY": "top-secret-token", "GROQ_MODEL": "model-configured-by-env"}
    )

    response = GroqLLMClient(settings).generate("plan_proposal", {"goal": "sample"}, "{}")

    request = captured["request"]
    sent_body = json.loads(request.data)
    assert request.full_url == groq.GROQ_CHAT_COMPLETIONS_URL
    assert request.get_header("Authorization") == "Bearer top-secret-token"
    assert captured["timeout"] == groq.GROQ_REQUEST_TIMEOUT_SECONDS
    assert sent_body["model"] == "model-configured-by-env"
    assert sent_body["response_format"] == {"type": "json_object"}
    assert sent_body["max_completion_tokens"] == groq.MAX_GROQ_COMPLETION_TOKENS
    assert "tools" not in sent_body
    assert response.content == '{"ok":true}'
    assert "top-secret-token" not in repr(settings)


def test_groq_adapter_requires_environment_configuration_without_leaking_key() -> None:
    client = GroqLLMClient(AgentSettings())

    with pytest.raises(GroqLLMError) as failure:
        client.generate("plan_proposal", {}, "{}")

    assert failure.value.category == "missing_configuration"
    assert "secret" not in str(failure.value).lower()


def test_groq_adapter_rejects_unapproved_operation_before_network() -> None:
    client = GroqLLMClient(
        AgentSettings.from_env({"GROQ_API_KEY": "secret", "GROQ_MODEL": "test-model"})
    )

    with pytest.raises(GroqLLMError) as failure:
        client.generate("execute_python", {}, "{}")

    assert failure.value.category == "unsupported_operation"
