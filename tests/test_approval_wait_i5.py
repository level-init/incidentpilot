"""I5: AWAITING_APPROVAL durable wait — timeout never executes; survives kill."""

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

from incidentpilot_shared.approval_signals import ApprovalDecisionSignal  # noqa: E402
from incidentpilot_worker.activities.approval_wait import (  # noqa: E402
    handle_approval_timeout,
)
from incidentpilot_worker.activities.incident_transitions import (  # noqa: E402
    advance_incident_state,
    load_incident_snapshot,
)
from incidentpilot_worker.workflows.incident_workflow import (  # noqa: E402
    IncidentWorkflow,
    IncidentWorkflowInput,
)
from incidentpilot_worker.workflows.timers import (  # noqa: E402
    TIMER_APPROVAL_TIMEOUT,
    WorkflowTimerConfig,
)

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="i5-test-act")


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.approval LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(not _db_available(), reason="Postgres not reachable"),
    pytest.mark.asyncio,
]


def _seed_awaiting(incident_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Incident AWAITING_APPROVAL + PENDING approval for ROLLBACK v1."""
    action_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'I5 wait', 3)
            """,
            (str(incident_id), f"INC-I5-{incident_id.hex[:8]}"),
        )
        cur.execute(
            """
            INSERT INTO domain.action (
                id, incident_id, action_type, current_version, status, proposed_by
            ) VALUES (%s, %s, 'ROLLBACK_DEPLOYMENT', 1, 'AWAITING_APPROVAL', 'system')
            """,
            (str(action_id), str(incident_id)),
        )
        cur.execute(
            """
            INSERT INTO domain.action_version (
                action_id, version, action_type, proposed_by
            ) VALUES (%s, 1, 'ROLLBACK_DEPLOYMENT', 'system')
            """,
            (str(action_id),),
        )
        cur.execute(
            """
            INSERT INTO domain.policy_decision (
                action_id, action_version, decision, reason
            ) VALUES (%s, 1, 'REQUIRE_APPROVAL', 'i5')
            """,
            (str(action_id),),
        )
        cur.execute(
            """
            INSERT INTO domain.approval (id, action_id, action_version, status)
            VALUES (%s, %s, 1, 'PENDING')
            """,
            (str(approval_id), str(action_id)),
        )
        conn.commit()
    return action_id, approval_id


@pytest.fixture()
def incident_id() -> Iterator[uuid.UUID]:
    iid = uuid.uuid4()
    _seed_awaiting(iid)
    yield iid


def _worker(env: WorkflowEnvironment, task_queue: str) -> Worker:
    return Worker(
        env.client,
        task_queue=task_queue,
        workflows=[IncidentWorkflow],
        activities=[
            load_incident_snapshot,
            advance_incident_state,
            handle_approval_timeout,
        ],
        activity_executor=_ACTIVITY_EXECUTOR,
    )


async def test_timeout_does_not_execute_remediation(incident_id: uuid.UUID) -> None:
    task_queue = f"test-i5-timeout-{uuid.uuid4().hex[:8]}"
    timers = WorkflowTimerConfig(approval_timeout_seconds=2)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with _worker(env, task_queue):
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(
                    incident_id=str(incident_id),
                    wait_for_approval=True,
                    timers=timers,
                ),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )
            await env.sleep(timedelta(seconds=3))
            result = await handle.result()
            assert result == "DIAGNOSED"
            assert await handle.query(IncidentWorkflow.approval_wait_result) == "TIMEOUT"
            assert await handle.query(IncidentWorkflow.remediation_executed) is False
            assert (
                await handle.query(IncidentWorkflow.timer_fire_count, TIMER_APPROVAL_TIMEOUT)
                == 1
            )

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ap.status, a.status
            FROM domain.approval ap
            JOIN domain.action a ON a.id = ap.action_id
            WHERE a.incident_id = %s
            """,
            (str(incident_id),),
        )
        approval_status, action_status = cur.fetchone()
        assert approval_status == "EXPIRED"
        assert action_status == "CANCELLED"
        cur.execute(
            "SELECT state FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        assert cur.fetchone()[0] == "DIAGNOSED"
        cur.execute(
            """
            SELECT 1 FROM domain.execution_attempt ea
            JOIN domain.action a ON a.id = ea.action_id
            WHERE a.incident_id = %s
            """,
            (str(incident_id),),
        )
        assert cur.fetchone() is None


async def test_approve_signal_unblocks_without_execute(incident_id: uuid.UUID) -> None:
    task_queue = f"test-i5-approve-{uuid.uuid4().hex[:8]}"
    timers = WorkflowTimerConfig(approval_timeout_seconds=30 * 60)
    action_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    # Replace seed ids — fixture already seeded; look them up.
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM domain.action WHERE incident_id = %s",
            (str(incident_id),),
        )
        action_id = uuid.UUID(str(cur.fetchone()[0]))
        cur.execute(
            "SELECT id FROM domain.approval WHERE action_id = %s",
            (str(action_id),),
        )
        approval_id = uuid.UUID(str(cur.fetchone()[0]))

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with _worker(env, task_queue):
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(
                    incident_id=str(incident_id),
                    wait_for_approval=True,
                    timers=timers,
                ),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )
            await handle.signal(
                IncidentWorkflow.approval_decision,
                ApprovalDecisionSignal(
                    decision_id=str(uuid.uuid4()),
                    approval_id=str(approval_id),
                    action_id=str(action_id),
                    action_version=1,
                    status="APPROVED",
                    decided_by="harness",
                ),
            )
            result = await handle.result()
            assert result == "AWAITING_APPROVAL"
            assert await handle.query(IncidentWorkflow.approval_wait_result) == "APPROVED"
            assert await handle.query(IncidentWorkflow.remediation_executed) is False
            assert (
                await handle.query(IncidentWorkflow.timer_fire_count, TIMER_APPROVAL_TIMEOUT)
                == 0
            )


async def test_approval_wait_survives_worker_kill(incident_id: uuid.UUID) -> None:
    task_queue = f"test-i5-kill-{uuid.uuid4().hex[:8]}"
    timers = WorkflowTimerConfig(approval_timeout_seconds=2)

    async with await WorkflowEnvironment.start_local() as env:
        worker = _worker(env, task_queue)
        worker_task = asyncio.create_task(worker.run())
        try:
            handle = await env.client.start_workflow(
                IncidentWorkflow.run,
                IncidentWorkflowInput(
                    incident_id=str(incident_id),
                    wait_for_approval=True,
                    timers=timers,
                ),
                id=f"incident-{incident_id}",
                task_queue=task_queue,
            )
            for _ in range(100):
                armed = await handle.query(IncidentWorkflow.timers_armed)
                if TIMER_APPROVAL_TIMEOUT in armed:
                    break
                await asyncio.sleep(0.05)
            else:
                raise TimeoutError("approval_timeout was not armed")

            assert await handle.query(IncidentWorkflow.remediation_executed) is False

            await worker.shutdown()
            await worker_task

            worker2 = _worker(env, task_queue)
            worker2_task = asyncio.create_task(worker2.run())
            try:
                result = await asyncio.wait_for(handle.result(), timeout=15)
                assert result == "DIAGNOSED"
                assert await handle.query(IncidentWorkflow.approval_wait_result) == "TIMEOUT"
                assert await handle.query(IncidentWorkflow.remediation_executed) is False
            finally:
                await worker2.shutdown()
                await worker2_task
        finally:
            if not worker_task.done():
                await worker.shutdown()
                await worker_task
