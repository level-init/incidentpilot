"""AlertProvider protocol — normalize vendor payloads to ``NormalizedAlert``."""

from __future__ import annotations

from typing import Any, Protocol

from incidentpilot_shared.alerts import NormalizedAlert


class AlertProvider(Protocol):
    """Inbound alert adapter: raw vendor JSON → normalized domain candidates."""

    name: str

    def normalize(self, payload: dict[str, Any]) -> list[NormalizedAlert]:
        """Return zero or more alerts; never writes ``domain.*``."""
        ...
