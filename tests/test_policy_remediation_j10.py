"""J10: Policy (+ L2 harness) → reserve → MITIGATING → execute rollback once."""

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

from incidentpilot_adapters.remediation import SimDeploymentWorld  # noqa: E402
from incidentpilot_api.app import app  # noqa: E402
from incidentpilot_api.temporal import set_temporal_client_override  # noqa: E402
from incidentpilot_worker.activities.approval_wait import (  # noqa: E402
    handle_approval_rejected,
    handle_approval_timeout,
)
from incidentpilot_worker.activities.approved_remediation import (  # noqa: E402
    handle_approval_approved,
    set_sim_deployment_world,
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

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="j10-act")


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


def _seed_l2_rollback() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    incident_id = uuid.uuid4()
    action_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    params = '{"revision": "prev", "deployment": "checkout"}'
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'J10 L2', 3)
            """,
            (str(incident_id), f"INC-J10-{incident_id.hex[:8]}"),
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
                action_id, version, action_type, parameters, proposed_by
            ) VALUES (%s, 1, 'ROLLBACK_DEPLOYMENT', %s::jsonb, 'system')
            """,
            (str(action_id), params),
        )
        cur.execute(
            """
            INSERT INTO domain.policy_decision (
                action_id, action_version, decision, reason
            ) VALUES (%s, 1, 'REQUIRE_APPROVAL', 'j10-l2')
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
            handle_approval_approved,
        ],
        activity_executor=_ACTIVITY_EXECUTOR,
    )


@pytest.fixture()
def world() -> Iterator[SimDeploymentWorld]:
    w = SimDeploymentWorld()
    w.seed("checkout", "bad")
    set_sim_deployment_world(w)
    yield w
    set_sim_deployment_world(None)


@pytest.mark.asyncio
async def test_level2_harness_executes_rollback_once(world: SimDeploymentWorld) -> None:
    incident_id, action_id, approval_id = _seed_l2_rollback()
    task_queue = f"test-j10-{uuid.uuid4().hex[:8]}"
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
                        execute_on_approval=True,
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
                        json={"status": "APPROVED"},
                    )
                assert res.status_code == 200, res.text

                result = await handle.result()
                assert result == "MITIGATING"
                assert await handle.query(IncidentWorkflow.approval_wait_result) == "APPROVED"
                assert await handle.query(IncidentWorkflow.remediation_executed) is True
        finally:
            set_temporal_client_override(None)

    assert world.observe("checkout") == "prev"
    assert world.apply_counts["checkout"] == 1

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT state FROM domain.execution_attempt
            WHERE action_id = %s AND action_version = 1
            """,
            (str(action_id),),
        )
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "RESERVED"
        cur.execute(
            "SELECT state FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        assert cur.fetchone()[0] == "MITIGATING"


def test_block_never_calls_adapter(world: SimDeploymentWorld) -> None:
    incident_id = uuid.uuid4()
    action_id = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'J10 BLOCK', 3)
            """,
            (str(incident_id), f"INC-J10B-{incident_id.hex[:8]}"),
        )
        cur.execute(
            """
            INSERT INTO domain.action (
                id, incident_id, action_type, current_version, status, proposed_by
            ) VALUES (%s, %s, 'ROLLBACK_DEPLOYMENT', 1, 'BLOCKED', 'system')
            """,
            (str(action_id), str(incident_id)),
        )
        cur.execute(
            """
            INSERT INTO domain.action_version (
                action_id, version, action_type, parameters, proposed_by
            ) VALUES (%s, 1, 'ROLLBACK_DEPLOYMENT',
                      '{"revision":"prev","deployment":"checkout"}'::jsonb, 'system')
            """,
            (str(action_id),),
        )
        cur.execute(
            """
            INSERT INTO domain.policy_decision (
                action_id, action_version, decision, reason
            ) VALUES (%s, 1, 'BLOCK', 'j10-block')
            """,
            (str(action_id),),
        )
        conn.commit()

    out = handle_approval_approved(
        {
            "incident_id": str(incident_id),
            "action_id": str(action_id),
            "action_version": 1,
        }
    )
    assert out["remediation_executed"] is False
    assert out["blocked"] is True
    assert out["adapter_execute_calls"] == 0
    assert world.apply_counts.get("checkout", 0) == 0

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM domain.execution_attempt WHERE action_id = %s",
            (str(action_id),),
        )
        assert cur.fetchone()[0] == 0
