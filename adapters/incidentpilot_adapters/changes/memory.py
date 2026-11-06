"""In-memory ChangeSource for tests and local stubs (G8)."""

from __future__ import annotations

from datetime import datetime

from incidentpilot_shared.changes import NormalizedChange


class MemoryChangeSource:
    """Seeded read-only store — no mutate / deploy APIs."""

    def __init__(self, name: str = "memory", changes: list[NormalizedChange] | None = None) -> None:
        self.name = name
        self._changes: list[NormalizedChange] = list(changes or [])

    def seed(self, change: NormalizedChange) -> None:
        """Test helper to load fixtures (not part of ChangeSource Protocol)."""
        self._changes.append(change)

    def list_changes(
        self,
        *,
        service: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[NormalizedChange]:
        out: list[NormalizedChange] = []
        for ch in self._changes:
            if service is not None and ch.service_key != service:
                continue
            if since is not None and ch.observed_at < since:
                continue
            if until is not None and ch.observed_at > until:
                continue
            out.append(ch)
        return out

    def fetch_change(self, source_ref: str) -> NormalizedChange | None:
        for ch in self._changes:
            if ch.source_ref == source_ref:
                return ch
        return None
