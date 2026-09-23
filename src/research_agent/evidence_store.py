"""Validated, run-local in-memory evidence ledger."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from research_agent.models import Evidence


class DuplicateEvidenceError(ValueError):
    """Raised when an evidence ID is reused for different evidence."""


class EvidenceStore:
    """Store validated evidence by goal and stable evidence ID.

    Re-adding an identical record is idempotent. Reusing its ID for different
    content is rejected so provenance cannot be silently overwritten.
    """

    def __init__(self) -> None:
        self._items: dict[UUID, Evidence] = {}
        self._goal_index: dict[UUID, list[UUID]] = {}

    def add(self, evidence: Evidence | dict[str, Any]) -> str:
        """Validate and add evidence, returning its canonical ID as a string."""
        validated = Evidence.model_validate(
            evidence.model_dump() if isinstance(evidence, Evidence) else evidence
        )
        existing = self._items.get(validated.evidence_id)
        if existing is not None:
            if existing == validated:
                return str(existing.evidence_id)
            raise DuplicateEvidenceError("evidence ID already belongs to another record")
        self._items[validated.evidence_id] = validated.model_copy(deep=True)
        self._goal_index.setdefault(validated.goal_id, []).append(validated.evidence_id)
        return str(validated.evidence_id)

    def get(self, evidence_id: UUID | str) -> Evidence:
        """Return a defensive copy of one evidence item."""
        try:
            key = evidence_id if isinstance(evidence_id, UUID) else UUID(evidence_id)
            return self._items[key].model_copy(deep=True)
        except (ValueError, KeyError):
            raise KeyError("evidence ID is not present in this run's store") from None

    def for_goal(self, goal_id: UUID | str) -> list[Evidence]:
        """Return goal-scoped evidence in insertion order."""
        try:
            key = goal_id if isinstance(goal_id, UUID) else UUID(goal_id)
        except ValueError:
            return []
        return [
            self._items[evidence_id].model_copy(deep=True)
            for evidence_id in self._goal_index.get(key, [])
        ]

    def all(self) -> list[Evidence]:
        """Return a defensive copy of every stored item."""
        return [item.model_copy(deep=True) for item in self._items.values()]
