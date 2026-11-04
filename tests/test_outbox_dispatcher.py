"""D4: outbox dispatcher → Temporal signals; crash + duplicate safe."""

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

from incidentpilot_shared.domain.outbox import (  # noqa: E402
    enqueue_outbox,
    fetch_pending_outbox,
    mark_outbox_published,
    release_outbox_lease,
)
from incidentpilot_shared.domain.transitions import IncidentState  # noqa: E402
from incidentpilot_worker.activities.incident_transitions import (  # noqa: E402
    advance_incident_state,
    load_incident_snapshot,
)
from incidentpilot_worker.commands import transition_incident_command  # noqa: E402
from incidentpilot_worker.outbox_dispatcher import (  # noqa: E402
    deliver_outbox_signal,
    dispatch_once,
)
from incidentpilot_worker.workflows.incident_workflow import (  # noqa: E402
    IncidentWorkflow,
    IncidentWorkflowInput,
)

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="d4-test-act")


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.outbox_message LIMIT 1")
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
            VALUES (%s, %s, 'DETECTED', 'D4 outbox', 1)
            """,
            (str(iid), f"INC-D4-{iid.hex[:8]}"),
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


def _outbox_status(message_id: uuid.UUID) -> str:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM domain.outbox_message WHERE id = %s",
            (str(message_id),),
        )
        row = cur.fetchone()
        assert row is not None
        return str(row[0])


def _latest_outbox_id(incident_id: uuid.UUID) -> uuid.UUID:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM domain.outbox_message
            WHERE aggregate_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
        assert row is not None
        return uuid.UUID(str(row[0]))


def _worker(env: WorkflowEnvironment, task_queue: str) -> Worker:
    return Worker(
        env.client,
        task_queue=task_queue,
        workflows=[IncidentWorkflow],
        activities=[load_incident_snapshot, advance_incident_state],
        activity_executor=_ACTIVITY_EXECUTOR,
    )


async def test_dispatch_signals_and_marks_published(incident_id: uuid.UUID) -> None:
    task_queue = f"test-d4-{uuid.uuid4().hex[:8]}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with _worker(env, task_queue):
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(
                    incident_id=str(incident_id),
                    wait_for_domain_event=True,
                ),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )
            for _ in range(100):
                if _pg_state(incident_id)[0] == "INVESTIGATING":
                    break
                await asyncio.sleep(0.05)
            else:
                raise TimeoutError("workflow did not reach INVESTIGATING")

            published = await dispatch_once(
                env.client,
                lease_seconds=5.0,
                aggregate_id=str(incident_id),
            )
            assert published >= 1
            result = await handle.result()
            assert result == "INVESTIGATING"
            assert await handle.query(IncidentWorkflow.domain_event_count) >= 1

    assert _pg_state(incident_id)[0] == "INVESTIGATING"


async def test_duplicate_dispatch_safe_no_double_transition(
    incident_id: uuid.UUID,
) -> None:
    """Re-signaling the same outbox message must not mutate Incident again."""
    with psycopg.connect(_dsn()) as conn:
        transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=1,
            to_state=IncidentState.TRIAGING,
            actor="api",
            commit=True,
        )
        transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=2,
            to_state=IncidentState.INVESTIGATING,
            actor="api",
            commit=True,
        )
    assert _pg_state(incident_id) == ("INVESTIGATING", 3)
    message_id = _latest_outbox_id(incident_id)

    task_queue = f"test-d4-dup-{uuid.uuid4().hex[:8]}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with _worker(env, task_queue):
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(
                    incident_id=str(incident_id),
                    wait_for_domain_event=True,
                ),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )
            with psycopg.connect(_dsn()) as conn:
                release_outbox_lease(conn, message_id)
                msgs = fetch_pending_outbox(
                    conn,
                    limit=20,
                    lease_seconds=0,
                    aggregate_id=str(incident_id),
                )
                conn.commit()
            target = next(m for m in msgs if m.id == message_id)
            await deliver_outbox_signal(env.client, target)
            await deliver_outbox_signal(env.client, target)
            with psycopg.connect(_dsn()) as conn:
                mark_outbox_published(conn, message_id)
                conn.commit()

            result = await handle.result()
            assert result == "INVESTIGATING"
            assert await handle.query(IncidentWorkflow.domain_event_count) == 1

    assert _pg_state(incident_id) == ("INVESTIGATING", 3)
    assert _outbox_status(message_id) == "published"


async def test_dispatcher_crash_mid_flight_eventually_signals(
    incident_id: uuid.UUID,
) -> None:
    """Domain commit survives; crash after signal before publish; retry delivers once."""
    with psycopg.connect(_dsn()) as conn:
        mid = enqueue_outbox(
            conn,
            aggregate_type="incident",
            aggregate_id=str(incident_id),
            event_type="incident.transitioned",
            payload={"from": "DETECTED", "to": "TRIAGING", "revision": 1},
        )
        conn.commit()

    task_queue = f"test-d4-crash-{uuid.uuid4().hex[:8]}"
    async with await WorkflowEnvironment.start_local() as env:
        async with _worker(env, task_queue):
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(
                    incident_id=str(incident_id),
                    wait_for_domain_event=True,
                ),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )

            with psycopg.connect(_dsn()) as conn:
                claimed = fetch_pending_outbox(
                    conn,
                    limit=5,
                    lease_seconds=60,
                    aggregate_id=str(incident_id),
                )
                conn.commit()
            target = next(m for m in claimed if m.id == mid)
            await deliver_outbox_signal(env.client, target)
            assert _outbox_status(mid) == "pending"

            with psycopg.connect(_dsn()) as conn:
                release_outbox_lease(conn, mid)
                conn.commit()
            published = await dispatch_once(
                env.client,
                lease_seconds=5.0,
                aggregate_id=str(incident_id),
            )
            assert published >= 1

            result = await handle.result()
            assert result == "INVESTIGATING"
            assert await handle.query(IncidentWorkflow.domain_event_count) == 1

    assert _outbox_status(mid) == "published"
    assert _pg_state(incident_id) == ("INVESTIGATING", 3)
