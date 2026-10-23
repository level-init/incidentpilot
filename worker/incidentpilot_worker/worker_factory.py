"""Build Temporal Workers for Freeze-9 queues (D1/D2)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from incidentpilot_shared.temporal_queues import TaskQueue
from incidentpilot_shared.temporal_runtime import queue_subscribe_ping
from incidentpilot_worker.activities.incident_transitions import (
    advance_incident_state,
    load_incident_snapshot,
)
from incidentpilot_worker.workflows.incident_workflow import IncidentWorkflow

# Sync (psycopg) activities require a thread pool executor.
_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ip-activity")


def build_worker(client: Client, task_queue: TaskQueue | str) -> Worker:
    queue = TaskQueue(str(task_queue)) if not isinstance(task_queue, TaskQueue) else task_queue

    if queue is TaskQueue.GENERAL:
        return Worker(
            client,
            task_queue=str(queue),
            workflows=[IncidentWorkflow],
            activities=[
                queue_subscribe_ping,
                load_incident_snapshot,
                advance_incident_state,
            ],
            activity_executor=_ACTIVITY_EXECUTOR,
        )

    # evidence / remediation: subscription only until later epics
    return Worker(
        client,
        task_queue=str(queue),
        workflows=[],
        activities=[queue_subscribe_ping],
    )
