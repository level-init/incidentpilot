"""D2: IncidentWorkflow DETECTED→TRIAGING→INVESTIGATING + crash-resume."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

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

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="d2-test-act")


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
    """Create a DETECTED incident. No teardown delete — timeline is append-only."""
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DETECTED', 'D2 workflow', 1)
            """,
            (str(iid), f"INC-D2-{iid.hex[:8]}"),
        )
        conn.commit()
    yield iid


def _pg_state(incident_id: uuid.UUID) -> tuple[str, int]:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT state, incident_revision FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        row = cur.fetchone()
        assert row is not None
        return str(row[0]), int(row[1])


def _incident_count(public_prefix: str) -> int:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM domain.incident WHERE public_id LIKE %s",
            (f"{public_prefix}%",),
        )
        return int(cur.fetchone()[0])


async def _wait_pg_state(
    incident_id: uuid.UUID,
    expected: str,
    *,
    timeout: float = 15.0,
) -> tuple[str, int]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        state, rev = _pg_state(incident_id)
        if state == expected:
            return state, rev
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"expected {expected}, last saw {state} rev={rev}")
        await asyncio.sleep(0.1)


def _worker(env: WorkflowEnvironment, task_queue: str) -> Worker:
    return Worker(
        env.client,
        task_queue=task_queue,
        workflows=[IncidentWorkflow],
        activities=[load_incident_snapshot, advance_incident_state],
        activity_executor=_ACTIVITY_EXECUTOR,
    )


async def test_workflow_reaches_investigating_postgres_matches(
    incident_id: uuid.UUID,
) -> None:
    task_queue = f"test-d2-{uuid.uuid4().hex[:8]}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with _worker(env, task_queue):
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(incident_id=str(incident_id)),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )
            result = await handle.result()

    assert result == "INVESTIGATING"
    state, rev = _pg_state(incident_id)
    assert state == "INVESTIGATING"
    assert rev == 3  # DETECTED@1 → TRIAGING@2 → INVESTIGATING@3


async def test_worker_kill_mid_triage_resumes_without_duplicate_incident(
    incident_id: uuid.UUID,
) -> None:
    public_prefix = f"INC-D2-{incident_id.hex[:8]}"
    task_queue = f"test-d2-crash-{uuid.uuid4().hex[:8]}"

    async with await WorkflowEnvironment.start_local() as env:
        worker = _worker(env, task_queue)
        worker_task = asyncio.create_task(worker.run())
        try:
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(
                    incident_id=str(incident_id),
                    wait_after_triaging=True,
                ),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )
            await _wait_pg_state(incident_id, "TRIAGING")

            # Kill worker mid-triage (after TRIAGING, before INVESTIGATING).
            await worker.shutdown()
            await worker_task
            assert _pg_state(incident_id)[0] == "TRIAGING"

            # Restart worker — durable workflow resumes; no new Incident row.
            worker2 = _worker(env, task_queue)
            worker2_task = asyncio.create_task(worker2.run())
            try:
                await handle.signal(IncidentWorkflow.proceed_after_triaging)
                result = await handle.result()
            finally:
                await worker2.shutdown()
                await worker2_task
        finally:
            if not worker_task.done():
                await worker.shutdown()
                await worker_task

    assert result == "INVESTIGATING"
    state, rev = _pg_state(incident_id)
    assert state == "INVESTIGATING"
    assert rev == 3
    assert _incident_count(public_prefix) == 1
