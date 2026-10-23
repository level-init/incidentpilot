"""Temporal task queue names + Freeze-9 consumer contracts (D1).

Queue topology isolates privilege classes without turning agents into
microservices. Workflow business logic lands in later Epic D tickets.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class TaskQueue(StrEnum):
    """Canonical Temporal task queue names."""

    GENERAL = "incidentpilot-general"
    EVIDENCE = "incidentpilot-evidence"
    REMEDIATION = "incidentpilot-remediation"


ALL_TASK_QUEUES: Final[tuple[TaskQueue, ...]] = (
    TaskQueue.GENERAL,
    TaskQueue.EVIDENCE,
    TaskQueue.REMEDIATION,
)


@dataclass(frozen=True, slots=True)
class QueueConsumerContract:
    """Which Freeze-9 process may poll a queue (privilege isolation)."""

    queue: TaskQueue
    consumer_process: str
    privilege_class: str
    description: str


# Freeze-9 deployable → queue mapping (authoritative for D1 docs + smoke).
QUEUE_CONSUMER_CONTRACTS: Final[tuple[QueueConsumerContract, ...]] = (
    QueueConsumerContract(
        queue=TaskQueue.GENERAL,
        consumer_process="incidentpilot-worker",
        privilege_class="orchestration",
        description=(
            "IncidentWorkflow + investigation/reasoning activities. "
            "No rollback keys, no GroundTruth, no privileged execute."
        ),
    ),
    QueueConsumerContract(
        queue=TaskQueue.EVIDENCE,
        consumer_process="evidence-worker",
        privilege_class="collector",
        description=(
            "Evidence producer / collector activities (metrics, logs, traces, changes). "
            "Deterministic processors only; not privileged remediation."
        ),
    ),
    QueueConsumerContract(
        queue=TaskQueue.REMEDIATION,
        consumer_process="remediation-worker",
        privilege_class="privileged-execute",
        description=(
            "Remediation execute / reconcile only. Holds privileged credentials; "
            "must not run investigation or GroundTruth workloads."
        ),
    ),
)


def contract_for(queue: TaskQueue) -> QueueConsumerContract:
    for contract in QUEUE_CONSUMER_CONTRACTS:
        if contract.queue is queue:
            return contract
    raise KeyError(queue)


def queues_for_process(consumer_process: str) -> tuple[TaskQueue, ...]:
    return tuple(
        c.queue for c in QUEUE_CONSUMER_CONTRACTS if c.consumer_process == consumer_process
    )
