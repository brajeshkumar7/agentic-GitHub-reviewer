from __future__ import annotations

import json
from io import BytesIO
from email.message import Message
from urllib.error import HTTPError
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
        {"GROQ_API_KEY": "top-secret-token", "GROQ_MODEL": "openai/gpt-oss-20b"}
    )

    response = GroqLLMClient(settings).generate("plan_proposal", {"goal": "sample"}, "{}")

    request = captured["request"]
    sent_body = json.loads(request.data)
    assert request.full_url == groq.GROQ_CHAT_COMPLETIONS_URL
    assert request.get_header("Authorization") == "Bearer top-secret-token"
    assert request.get_header("User-agent") == "research-intelligence-agent/0.1"
    assert captured["timeout"] == groq.GROQ_REQUEST_TIMEOUT_SECONDS
    assert sent_body["model"] == "openai/gpt-oss-20b"
    assert sent_body["response_format"] == {"type": "json_object"}
    assert sent_body["max_completion_tokens"] == groq.MAX_GROQ_COMPLETION_TOKENS
    assert sent_body["reasoning_effort"] == "low"
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


@pytest.mark.parametrize("header, expected", [("12.5", 12.5), ("86400", 86400.0),
    ("0", 0.0), ("-3", None), ("nan", None), ("inf", None), ("garbage", None), (None, None)])
def test_groq_preserves_safe_rate_limit_timing(monkeypatch, header, expected) -> None:
    headers = Message()
    if header is not None:
        headers["Retry-After"] = header
    def fail(request, timeout):
        raise HTTPError(request.full_url, 429, "Too Many Requests", headers,
            BytesIO(json.dumps({"error": {"code": "rate_limit_exceeded",
                "message": "sensitive provider content"}}).encode()))
    monkeypatch.setattr(groq, "urlopen", fail)
    client = GroqLLMClient(AgentSettings.from_env({"GROQ_API_KEY": "secret", "GROQ_MODEL": "fake"}))
    with pytest.raises(GroqLLMError) as caught:
        client.generate("plan_proposal", {}, "{}")
    assert caught.value.category == "http_429_rate_limit_exceeded"
    assert caught.value.retryable
    assert caught.value.retry_after_seconds == expected
    assert "sensitive" not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_retry_after_supports_http_date() -> None:
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    header = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
    assert 28 <= groq._retry_after_seconds(header) <= 30


def test_schema_is_sent_once_without_mutating_payload(monkeypatch) -> None:
    from research_agent.models import Plan
    schema = Plan.model_json_schema(by_alias=False)
    payload = {"schema": schema, "goal": "synthetic research"}
    captured = []
    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data))
        return FakeHTTPResponse(b'{"choices":[{"message":{"content":"{}"}}]}')
    monkeypatch.setattr(groq, "urlopen", fake_urlopen)
    client = GroqLLMClient(AgentSettings.from_env({"GROQ_API_KEY": "secret", "GROQ_MODEL": "fake"}))
    client.generate("plan_proposal", payload, json.dumps(schema))
    sent = json.loads(captured[0]["messages"][1]["content"])
    assert sent["expected_schema"] == schema
    assert "schema" not in sent["payload"]
    assert payload["schema"] == schema
    assert "reasoning_effort" not in captured[0]
