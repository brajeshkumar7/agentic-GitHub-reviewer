"""In-memory structured event logger with an optional visible trace sink."""

from __future__ import annotations

from collections.abc import Callable

from research_agent.models import ExecutionEvent


class EventLogger:
    """Keep a run's typed events and optionally render each event to a sink."""

    def __init__(self, sink: Callable[[ExecutionEvent], None] | None = None) -> None:
        self.events: list[ExecutionEvent] = []
        self._sink = sink

    def emit(self, event: ExecutionEvent) -> None:
        self.events.append(event)
        if self._sink is not None:
            self._sink(event)
