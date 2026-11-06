"""ChangeSource adapters — read-only; persist via ``upsert_change_command`` (G8)."""

from incidentpilot_adapters.changes.memory import MemoryChangeSource
from incidentpilot_adapters.changes.protocol import ChangeSource

__all__ = [
    "ChangeSource",
    "MemoryChangeSource",
]
