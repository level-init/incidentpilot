"""IncidentWorkflow identity + idempotent start (F5).

API starts workflows by name (no worker import). Worker owns the run
implementation; input shape is shared so payloads stay compatible.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from incidentpilot_shared.temporal_queues import TaskQueue

WORKFLOW_NAME = "IncidentWorkflow"


@dataclass
class IncidentWorkflowInput:
    """Payload for ``IncidentWorkflow.run`` (API start + worker + tests)."""

    incident_id: str
    wait_after_triaging: bool = False
    wait_for_domain_event: bool = False
    # G10: after INVESTIGATING, kick off default CollectCycleWorkflow (evidence queue).
    start_collect_cycle: bool = False
    # G6/G10: wait for EvidenceUpdated (default off for isolated D2 unit tests).
    wait_for_evidence_updated: bool = False
    # Worker types this as WorkflowTimerConfig; kept as Any for shared package.
    timers: Any | None = None
    wait_for_timer: str | None = None
    # I5: durable AWAITING_APPROVAL wait (signal vs approval_timeout).
    wait_for_approval: bool = False
    # J10: after APPROVED, reserve → MITIGATING → verify/execute (sim).
    execute_on_approval: bool = False
    # J7: durable validation_window then deterministic ValidationResult.
    wait_for_validation: bool = False
    execution_attempt_id: str | None = None


def incident_workflow_id(incident_id: str | UUID) -> str:
    return f"incident-{incident_id}"


def incident_workflow_task_queue() -> str:
    """Override with ``INCIDENT_WORKFLOW_TASK_QUEUE`` (tests / local)."""
    return os.environ.get(
        "INCIDENT_WORKFLOW_TASK_QUEUE",
        str(TaskQueue.GENERAL),
    )


async def ensure_incident_workflow_started(
    client: Client,
    incident_id: str | UUID,
    *,
    task_queue: str | None = None,
    start_collect_cycle: bool = True,
    wait_for_evidence_updated: bool = True,
) -> bool:
    """Idempotent start of IncidentWorkflow. True if newly started.

    Natural path (G10): kick off collect after INVESTIGATING and wait for
    EvidenceUpdated so EV-ids exist for reasoning. Unit tests that only need
    the state machine can pass ``start_collect_cycle=False``.
    """
    try:
        await client.start_workflow(
            WORKFLOW_NAME,
            IncidentWorkflowInput(
                incident_id=str(incident_id),
                start_collect_cycle=start_collect_cycle,
                wait_for_evidence_updated=wait_for_evidence_updated,
            ),
            id=incident_workflow_id(incident_id),
            task_queue=task_queue or incident_workflow_task_queue(),
        )
        return True
    except WorkflowAlreadyStartedError:
        return False
