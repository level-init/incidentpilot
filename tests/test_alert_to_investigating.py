"""F5: AM webhook → correlate → IncidentWorkflow → INVESTIGATING."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "api",
    ROOT / "shared",
    ROOT / "worker",
    ROOT / "adapters",
):
    sys.path.insert(0, str(p))

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("fastapi")
pytest.importorskip("temporalio")
pytest.importorskip("pytest_asyncio")

from fastapi.testclient import TestClient  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402
from incidentpilot_api.temporal import set_temporal_client_override  # noqa: E402
from incidentpilot_shared.incident_workflow import (  # noqa: E402
    ensure_incident_workflow_started,
    incident_workflow_id,
)
from incidentpilot_worker.activities.incident_transitions import (  # noqa: E402
    advance_incident_state,
    load_incident_snapshot,
)
from incidentpilot_worker.workflows.incident_workflow import IncidentWorkflow  # noqa: E402

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="f5-test-act")
PATH = "/webhooks/alerts/alertmanager"


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


def _pg_state(incident_id: str) -> tuple[str, int]:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT state, incident_revision FROM domain.incident WHERE id = %s",
            (incident_id,),
        )
        row = cur.fetchone()
        assert row is not None
        return str(row[0]), int(row[1])


async def _wait_investigating(incident_id: str, *, timeout: float = 20.0) -> tuple[str, int]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        state, rev = _pg_state(incident_id)
        if state == "INVESTIGATING":
            return state, rev
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"expected INVESTIGATING, last saw {state} rev={rev}")
        await asyncio.sleep(0.1)


@pytest.fixture()
def am_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-am-webhook-token"
    monkeypatch.setenv("ALERTMANAGER_WEBHOOK_TOKEN", token)
    monkeypatch.delenv("ALERTMANAGER_BASIC_USER", raising=False)
    monkeypatch.delenv("ALERTMANAGER_BASIC_PASSWORD", raising=False)
    monkeypatch.delenv("ALERTMANAGER_HEADER_VALUE", raising=False)
    return token


async def test_ensure_start_is_idempotent() -> None:
    task_queue = f"test-f5-idemp-{uuid.uuid4().hex[:8]}"
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DETECTED', 'F5 idempotent', 1)
            """,
            (str(iid), f"INC-F5I-{iid.hex[:8]}"),
        )
        conn.commit()

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[IncidentWorkflow],
            activities=[load_incident_snapshot, advance_incident_state],
            activity_executor=_ACTIVITY_EXECUTOR,
        ):
            # State-machine-only: skip G10 collect wait (no evidence worker here).
            first = await ensure_incident_workflow_started(
                env.client,
                iid,
                task_queue=task_queue,
                start_collect_cycle=False,
                wait_for_evidence_updated=False,
            )
            second = await ensure_incident_workflow_started(
                env.client,
                iid,
                task_queue=task_queue,
                start_collect_cycle=False,
                wait_for_evidence_updated=False,
            )
            handle = env.client.get_workflow_handle(incident_workflow_id(iid))
            result = await handle.result()

    assert first is True
    assert second is False
    assert result == "INVESTIGATING"
    assert _pg_state(str(iid))[0] == "INVESTIGATING"


async def test_am_webhook_reaches_investigating(
    am_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_queue = f"test-f5-am-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("INCIDENT_WORKFLOW_TASK_QUEUE", task_queue)
    pid = os.getpid()
    uid = uuid.uuid4().hex[:8]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        set_temporal_client_override(env.client)
        try:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[IncidentWorkflow],
                activities=[load_incident_snapshot, advance_incident_state],
                activity_executor=_ACTIVITY_EXECUTOR,
            ):
                with TestClient(app) as client:
                    res = client.post(
                        PATH,
                        json={
                            "receiver": "incidentpilot",
                            "status": "firing",
                            "alerts": [
                                {
                                    "status": "firing",
                                    "labels": {
                                        "alertname": "F5Checkout",
                                        "service": "checkout",
                                        "uid": uid,
                                    },
                                    "annotations": {"summary": f"f5-{pid}-{uid}"},
                                }
                            ],
                        },
                        headers={
                            "Authorization": f"Bearer {am_token}",
                            "Idempotency-Key": f"f5-am-{pid}-{uid}",
                        },
                    )
                assert res.status_code == 202, res.text
                incident_id = res.json()["incident_ids"][0]
                state, rev = await _wait_investigating(incident_id)
        finally:
            set_temporal_client_override(None)

    assert state == "INVESTIGATING"
    assert rev == 3
