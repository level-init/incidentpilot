"""Build Temporal Workers for Freeze-9 queues (D1/D2/G7).

Evidence collector imports are lazy so the general worker process never loads
Prom/Loki/Tempo clients (G7 — no source creds on orchestration).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from incidentpilot_shared.temporal_queues import TaskQueue
from incidentpilot_shared.temporal_runtime import queue_subscribe_ping
from incidentpilot_worker.activities.collector_trigger import trigger_collect_cycle
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
                trigger_collect_cycle,
            ],
            activity_executor=_ACTIVITY_EXECUTOR,
        )

    if queue is TaskQueue.EVIDENCE:
        # Lazy: keep telemetry clients out of the general process import graph.
        from incidentpilot_worker.activities.collect_cycle import (
            run_collect_cycle,
            validate_collect_job_scope,
        )
        from incidentpilot_worker.activities.collectors import (
            collect_loki_logs,
            collect_prometheus_metrics,
            collect_tempo_traces,
        )
        from incidentpilot_worker.workflows.collect_cycle import CollectCycleWorkflow

        return Worker(
            client,
            task_queue=str(queue),
            workflows=[CollectCycleWorkflow],
            activities=[
                queue_subscribe_ping,
                collect_prometheus_metrics,
                collect_loki_logs,
                collect_tempo_traces,
                validate_collect_job_scope,
                run_collect_cycle,
            ],
            activity_executor=_ACTIVITY_EXECUTOR,
        )

    # remediation: subscription only until later epics
    return Worker(
        client,
        task_queue=str(queue),
        workflows=[],
        activities=[queue_subscribe_ping],
    )
