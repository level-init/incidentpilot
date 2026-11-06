"""CollectJob schema + EvidenceUpdated signal payload (G6).

Jobs run on ``incidentpilot-evidence`` (tq-evidence-collect). Landing on that
queue is privilege isolation only — scope is validated server-side before
collect / signal. Queue ≠ authz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final
from uuid import UUID, uuid4

ALLOWED_COLLECTORS: Final[frozenset[str]] = frozenset({"metrics", "logs", "traces"})
DEFAULT_COLLECTORS: Final[tuple[str, ...]] = ("metrics", "logs", "traces")


@dataclass
class CollectJob:
    """Bounded evidence collect cycle for one incident."""

    incident_id: str
    environment: str
    cycle_id: str = field(default_factory=lambda: str(uuid4()))
    window_start: float | None = None
    window_end: float | None = None
    collectors: tuple[str, ...] = DEFAULT_COLLECTORS

    def __post_init__(self) -> None:
        if not self.incident_id:
            raise ValueError("CollectJob.incident_id is required")
        if not self.environment:
            raise ValueError("CollectJob.environment is required")
        if not self.cycle_id:
            raise ValueError("CollectJob.cycle_id is required")
        # Temporal may decode lists; normalize to tuple of allowed names.
        names = tuple(str(c) for c in self.collectors)
        unknown = sorted(set(names) - ALLOWED_COLLECTORS)
        if unknown:
            raise ValueError(f"unsupported collectors: {unknown}")
        if not names:
            raise ValueError("CollectJob.collectors must be non-empty")
        self.collectors = names


@dataclass
class EvidenceUpdated:
    """Cycle-completed signal to IncidentWorkflow (not an outbox domain event)."""

    incident_id: str
    cycle_id: str
    evidence_ids: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    inserted_count: int = 0


def collect_cycle_workflow_id(incident_id: str | UUID, cycle_id: str) -> str:
    return f"collect-{incident_id}-{cycle_id}"
