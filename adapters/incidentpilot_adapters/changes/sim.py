"""Sim ChangeSource — scenario catalog for local / demo evidence collect (G9)."""

from __future__ import annotations

from datetime import UTC, datetime

from incidentpilot_adapters.changes.catalog import scenario_changes_at
from incidentpilot_shared.changes import NormalizedChange


class SimChangeSource:
    """Read-only change view for the simulated world (no mutate / deploy APIs)."""

    def __init__(self, name: str = "sim") -> None:
        self.name = name

    def list_changes(
        self,
        *,
        service: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[NormalizedChange]:
        # Stamp catalog at window end (or now) so DEPLOYMENT lands in the collect window.
        stamp = until or datetime.now(tz=UTC)
        out: list[NormalizedChange] = []
        for ch in scenario_changes_at(stamp):
            if service is not None and ch.service_key != service:
                continue
            if since is not None and ch.observed_at < since:
                continue
            if until is not None and ch.observed_at > until:
                continue
            out.append(ch)
        return out

    def fetch_change(self, source_ref: str) -> NormalizedChange | None:
        stamp = datetime.now(tz=UTC)
        for ch in scenario_changes_at(stamp):
            if ch.source_ref == source_ref:
                return ch
        return None
