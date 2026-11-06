"""ChangeSource adapters — read-only; persist via ``upsert_change_command`` (G8/G9)."""

from incidentpilot_adapters.changes.memory import MemoryChangeSource
from incidentpilot_adapters.changes.protocol import ChangeSource
from incidentpilot_adapters.changes.sim import SimChangeSource

__all__ = [
    "ChangeSource",
    "MemoryChangeSource",
    "SimChangeSource",
]
