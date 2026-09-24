"""Structured in-memory and JSONL event sinks with secret-safe metadata."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from research_agent.models import ExecutionEvent


_SENSITIVE_KEY = re.compile(
    r"(api.?key|secret|token|password|credential|authorization)", re.I
)
_BEARER_VALUE = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_GROQ_KEY = re.compile(r"\bgsk_[A-Za-z0-9_-]{8,}\b")
_INLINE_SECRET = re.compile(
    r"(?i)\b(api[_ -]?key|secret|token|password|authorization)\s*[:=]\s*[^\s,;]+"
)


def _redact(value: Any, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = _BEARER_VALUE.sub(r"\1[REDACTED]", value)
        value = _INLINE_SECRET.sub(r"\1=[REDACTED]", value)
        return _GROQ_KEY.sub("[REDACTED]", value)
    return value


def redact_text(value: str) -> str:
    """Redact recognizable secret encodings from user-visible text fields."""
    safe_value = _redact(value)
    return safe_value if isinstance(safe_value, str) else "[REDACTED]"


def sanitize_event(event: ExecutionEvent) -> ExecutionEvent:
    """Return a validated event with secret-like metadata and text redacted."""
    payload = event.model_dump(mode="python")
    payload["metadata"] = _redact(payload["metadata"])
    return ExecutionEvent.model_validate(payload)


class EventLogger:
    """Keep typed events and optionally forward safe events to a trace sink."""

    def __init__(self, sink: Callable[[ExecutionEvent], None] | None = None) -> None:
        self.events: list[ExecutionEvent] = []
        self._sink = sink

    def emit(self, event: ExecutionEvent) -> None:
        safe_event = sanitize_event(event)
        self.events.append(safe_event)
        if self._sink is not None:
            self._sink(safe_event)


class JsonlEventLogger(EventLogger):
    """Append one validated, redacted JSON event per line to a UTF-8 file."""

    def __init__(
        self,
        path: str | Path,
        sink: Callable[[ExecutionEvent], None] | None = None,
    ) -> None:
        super().__init__(sink=sink)
        self.path = Path(path)

    def emit(self, event: ExecutionEvent) -> None:
        safe_event = sanitize_event(event)
        self.events.append(safe_event)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(safe_event.model_dump_json() + "\n")
            stream.flush()
        if self._sink is not None:
            self._sink(safe_event)
