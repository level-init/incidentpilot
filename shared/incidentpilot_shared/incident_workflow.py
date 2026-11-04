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
    # Worker types this as WorkflowTimerConfig; kept as Any for shared package.
    timers: Any | None = None
    wait_for_timer: str | None = None


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
) -> bool:
    """Idempotent start of IncidentWorkflow. True if newly started."""
    try:
        await client.start_workflow(
            WORKFLOW_NAME,
            IncidentWorkflowInput(incident_id=str(incident_id)),
            id=incident_workflow_id(incident_id),
            task_queue=task_queue or incident_workflow_task_queue(),
        )
        return True
    except WorkflowAlreadyStartedError:
        return False
