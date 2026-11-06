"""CollectJob schema + EvidenceUpdated + start helper (G6/G7).

Jobs run on ``incidentpilot-evidence`` (tq-evidence-collect). Landing on that
queue is privilege isolation only — scope is validated server-side before
collect / signal. Queue ≠ authz.

G7: general worker starts cycles via ``ensure_collect_cycle_started`` (by name)
without Prom/Loki/Tempo clients or env reads.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID, uuid4

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from incidentpilot_shared.temporal_queues import TaskQueue

ALLOWED_COLLECTORS: Final[frozenset[str]] = frozenset(
    {"metrics", "logs", "traces", "changes"}
)
DEFAULT_COLLECTORS: Final[tuple[str, ...]] = ("metrics", "logs", "traces", "changes")
COLLECT_CYCLE_WORKFLOW_NAME: Final[str] = "CollectCycleWorkflow"


@dataclass
class CollectJob:
    """Bounded evidence collect cycle for one incident."""

    incident_id: str
    environment: str
    cycle_id: str = field(default_factory=lambda: str(uuid4()))
    window_start: float | None = None
    window_end: float | None = None
    collectors: tuple[str, ...] = DEFAULT_COLLECTORS
    # Optional PromQL / LogQL / TraceQL for single-collector triggers (G7).
    query: str | None = None

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


def collect_cycle_task_queue() -> str:
    """Evidence queue (override ``COLLECT_CYCLE_TASK_QUEUE`` in tests)."""
    return os.environ.get("COLLECT_CYCLE_TASK_QUEUE", str(TaskQueue.EVIDENCE))


async def ensure_collect_cycle_started(
    client: Client,
    job: CollectJob,
    *,
    task_queue: str | None = None,
) -> bool:
    """Idempotent start of CollectCycleWorkflow on the evidence queue. True if new."""
    try:
        await client.start_workflow(
            COLLECT_CYCLE_WORKFLOW_NAME,
            job,
            id=collect_cycle_workflow_id(job.incident_id, job.cycle_id),
            task_queue=task_queue or collect_cycle_task_queue(),
        )
        return True
    except WorkflowAlreadyStartedError:
        return False
