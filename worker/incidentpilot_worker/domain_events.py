"""Domain → workflow signal envelopes (D4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DomainEventEnvelope:
    """Payload signaled to IncidentWorkflow (idempotent by message_id)."""

    message_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]
