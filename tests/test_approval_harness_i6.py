"""I6: Eval/test Approval harness — approve resumes; reject replans."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("fastapi")
pytest.importorskip("temporalio")
pytest.importorskip("pytest_asyncio")

from fastapi.testclient import TestClient  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402
from incidentpilot_api.temporal import set_temporal_client_override  # noqa: E402
from incidentpilot_worker.activities.approval_wait import (  # noqa: E402
    handle_approval_rejected,
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
from incidentpilot_worker.workflows.timers import WorkflowTimerConfig  # noqa: E402

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="i6-test-act")


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
]


def _seed_awaiting() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    incident_id = uuid.uuid4()
    action_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'I6 harness', 3)
            """,
            (str(incident_id), f"INC-I6-{incident_id.hex[:8]}"),
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
            ) VALUES (%s, 1, 'REQUIRE_APPROVAL', 'i6')
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
    return incident_id, action_id, approval_id


def _worker(env: WorkflowEnvironment, task_queue: str) -> Worker:
    return Worker(
        env.client,
        task_queue=task_queue,
        workflows=[IncidentWorkflow],
        activities=[
            load_incident_snapshot,
            advance_incident_state,
            handle_approval_timeout,
            handle_approval_rejected,
        ],
        activity_executor=_ACTIVITY_EXECUTOR,
    )


@pytest.fixture()
def seeded() -> Iterator[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    yield _seed_awaiting()


@pytest.mark.asyncio
async def test_harness_approve_resumes_workflow(
    seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    incident_id, _action_id, approval_id = seeded
    task_queue = f"test-i6-approve-{uuid.uuid4().hex[:8]}"
    timers = WorkflowTimerConfig(approval_timeout_seconds=30 * 60)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        set_temporal_client_override(env.client)
        try:
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
                # Let workflow reach wait_condition before harness decide.
                await asyncio.sleep(0.05)

                with TestClient(app) as client:
                    res = client.post(
                        f"/eval/approvals/{approval_id}/decide",
                        headers={"Authorization": "Bearer local-dev-evaluator"},
                        json={"status": "APPROVED"},
                    )
                assert res.status_code == 200, res.text
                body = res.json()
                assert body["approval"]["status"] == "APPROVED"
                assert body["decided_by"].startswith("harness:")
                assert body["workflow_signaled"] is True

                result = await handle.result()
                assert result == "AWAITING_APPROVAL"
                assert await handle.query(IncidentWorkflow.approval_wait_result) == "APPROVED"
                assert await handle.query(IncidentWorkflow.remediation_executed) is False
        finally:
            set_temporal_client_override(None)

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, decided_by FROM domain.approval WHERE id = %s",
            (str(approval_id),),
        )
        status, decided_by = cur.fetchone()
        assert status == "APPROVED"
        assert str(decided_by).startswith("harness:")


@pytest.mark.asyncio
async def test_harness_reject_replans(
    seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    incident_id, _action_id, approval_id = seeded
    task_queue = f"test-i6-reject-{uuid.uuid4().hex[:8]}"
    timers = WorkflowTimerConfig(approval_timeout_seconds=30 * 60)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        set_temporal_client_override(env.client)
        try:
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
                await asyncio.sleep(0.05)

                with TestClient(app) as client:
                    res = client.post(
                        f"/eval/approvals/{approval_id}/decide",
                        headers={"Authorization": "Bearer local-dev-evaluator"},
                        json={"status": "REJECTED"},
                    )
                assert res.status_code == 200, res.text
                assert res.json()["approval"]["status"] == "REJECTED"

                result = await handle.result()
                assert result == "DIAGNOSED"
                assert await handle.query(IncidentWorkflow.approval_wait_result) == "REJECTED"
                assert await handle.query(IncidentWorkflow.remediation_executed) is False
        finally:
            set_temporal_client_override(None)

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        assert cur.fetchone()[0] == "DIAGNOSED"
        cur.execute(
            "SELECT status FROM domain.approval WHERE id = %s",
            (str(approval_id),),
        )
        assert cur.fetchone()[0] == "REJECTED"
        cur.execute(
            """
            SELECT 1 FROM domain.execution_attempt ea
            JOIN domain.action a ON a.id = ea.action_id
            WHERE a.incident_id = %s
            """,
            (str(incident_id),),
        )
        assert cur.fetchone() is None


def test_ops_responder_cannot_use_harness_endpoint() -> None:
    _incident_id, _action_id, approval_id = _seed_awaiting()
    with TestClient(app) as client:
        res = client.post(
            f"/eval/approvals/{approval_id}/decide",
            headers={"Authorization": "Bearer local-dev"},
            json={"status": "APPROVED"},
        )
    assert res.status_code == 403, res.text
