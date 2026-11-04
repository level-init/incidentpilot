"""D5: durable investigation / approval / validation timers survive worker kill."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("temporalio")
pytest.importorskip("pytest_asyncio")

from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from incidentpilot_worker.activities.incident_transitions import (  # noqa: E402
    advance_incident_state,
    load_incident_snapshot,
)
from incidentpilot_worker.workflows.incident_workflow import (  # noqa: E402
    IncidentWorkflow,
    IncidentWorkflowInput,
)
from incidentpilot_worker.workflows.timers import (  # noqa: E402
    ALL_TIMER_NAMES,
    TIMER_APPROVAL_TIMEOUT,
    TIMER_INVESTIGATION_DEADLINE,
    TIMER_VALIDATION_WINDOW,
    WorkflowTimerConfig,
)

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="d5-test-act")


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.incident LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(not _db_available(), reason="Postgres not reachable"),
    pytest.mark.asyncio,
]


@pytest.fixture()
def incident_id() -> Iterator[uuid.UUID]:
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DETECTED', 'D5 timers', 1)
            """,
            (str(iid), f"INC-D5-{iid.hex[:8]}"),
        )
        conn.commit()
    yield iid


def _worker(env: WorkflowEnvironment, task_queue: str) -> Worker:
    return Worker(
        env.client,
        task_queue=task_queue,
        workflows=[IncidentWorkflow],
        activities=[load_incident_snapshot, advance_incident_state],
        activity_executor=_ACTIVITY_EXECUTOR,
    )


async def test_all_three_timers_register_and_fire_once(incident_id: uuid.UUID) -> None:
    task_queue = f"test-d5-{uuid.uuid4().hex[:8]}"
    timers = WorkflowTimerConfig(
        investigation_deadline_seconds=10 * 60,
        approval_timeout_seconds=20 * 60,
        validation_window_seconds=30 * 60,
    )
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with _worker(env, task_queue):
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(incident_id=str(incident_id), timers=timers),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )
            await env.sleep(timedelta(minutes=31))
            result = await handle.result()
            assert result == "INVESTIGATING"
            armed = await handle.query(IncidentWorkflow.timers_armed)
            assert set(armed) == set(ALL_TIMER_NAMES)
            for name in ALL_TIMER_NAMES:
                assert await handle.query(IncidentWorkflow.timer_fire_count, name) == 1


async def test_timer_fires_once_after_worker_kill(incident_id: uuid.UUID) -> None:
    """Kill worker while investigation deadline is armed; restart → fires once."""
    task_queue = f"test-d5-kill-{uuid.uuid4().hex[:8]}"
    # Short real timers — Temporal server tracks them across worker death.
    timers = WorkflowTimerConfig(
        investigation_deadline_seconds=2,
        approval_timeout_seconds=60,
        validation_window_seconds=60,
    )

    async with await WorkflowEnvironment.start_local() as env:
        worker = _worker(env, task_queue)
        worker_task = asyncio.create_task(worker.run())
        try:
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(
                    incident_id=str(incident_id),
                    timers=timers,
                    wait_for_timer=TIMER_INVESTIGATION_DEADLINE,
                ),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )
            for _ in range(100):
                armed = await handle.query(IncidentWorkflow.timers_armed)
                if TIMER_INVESTIGATION_DEADLINE in armed:
                    break
                await asyncio.sleep(0.05)
            else:
                raise TimeoutError("timer was not armed")

            assert (
                await handle.query(IncidentWorkflow.timer_fire_count, TIMER_INVESTIGATION_DEADLINE)
                == 0
            )

            # Kill worker mid-timer (server keeps the durable timer).
            await worker.shutdown()
            await worker_task

            worker2 = _worker(env, task_queue)
            worker2_task = asyncio.create_task(worker2.run())
            try:
                result = await asyncio.wait_for(handle.result(), timeout=15)
                assert result == "INVESTIGATING"
                assert (
                    await handle.query(
                        IncidentWorkflow.timer_fire_count, TIMER_INVESTIGATION_DEADLINE
                    )
                    == 1
                )
                assert (
                    await handle.query(IncidentWorkflow.timer_fire_count, TIMER_APPROVAL_TIMEOUT)
                    == 0
                )
                assert (
                    await handle.query(IncidentWorkflow.timer_fire_count, TIMER_VALIDATION_WINDOW)
                    == 0
                )
            finally:
                await worker2.shutdown()
                await worker2_task
        finally:
            if not worker_task.done():
                await worker.shutdown()
                await worker_task
