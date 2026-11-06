"""ChangeSource protocol — read-only change candidates (G8).

Adapters list/fetch only. No deploy / rollback / mutate methods — remediation
stays on the policy → execution_attempt → remediation-worker path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from incidentpilot_shared.changes import NormalizedChange


class ChangeSource(Protocol):
    """Outbound change-intelligence client: read vendor history only."""

    name: str

    def list_changes(
        self,
        *,
        service: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[NormalizedChange]:
        """Return matching changes; never writes ``domain.*``."""
        ...

    def fetch_change(self, source_ref: str) -> NormalizedChange | None:
        """Lookup by vendor source_ref; never writes ``domain.*``."""
        ...
