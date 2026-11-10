"""K3: Slack approve/reject → ApprovalDecision; stale version visible."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

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
from incidentpilot_api.slack_signing import compute_slack_signature  # noqa: E402
from incidentpilot_api.temporal import set_temporal_client_override  # noqa: E402
from incidentpilot_shared.slack_approval import (  # noqa: E402
    STALE_CODE,
    encode_slack_approval_value,
    parse_slack_approval_intent,
)
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

_ACTIVITY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="k3-test-act")
PATH = "/webhooks/slack/interactions"
SECRET = "test-slack-signing-secret-k3"


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.slack_interaction LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(not _db_available(), reason="Postgres / K2 migration not reachable"),
]


def test_parse_and_encode_roundtrip() -> None:
    aid = uuid.uuid4()
    acid = uuid.uuid4()
    value = encode_slack_approval_value(
        approval_id=aid,
        action_id=acid,
        action_version=2,
        decision="REJECTED",
    )
    payload = {
        "type": "block_actions",
        "actions": [{"action_id": "ip_reject", "value": value}],
    }
    intent = parse_slack_approval_intent(payload)
    assert intent is not None
    assert intent.approval_id == aid
    assert intent.action_id == acid
    assert intent.action_version == 2
    assert intent.decision == "REJECTED"


def _seed_awaiting() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    incident_id = uuid.uuid4()
    action_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'K3 slack', 3)
            """,
            (str(incident_id), f"INC-K3-{incident_id.hex[:8]}"),
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
            ) VALUES (
                %s, 1, 'ROLLBACK_DEPLOYMENT',
                '{"revision":"prev","deployment":"checkout"}'::jsonb, 'system'
            )
            """,
            (str(action_id),),
        )
        cur.execute(
            """
            INSERT INTO domain.policy_decision (
                action_id, action_version, decision, reason
            ) VALUES (%s, 1, 'REQUIRE_APPROVAL', 'k3')
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


def _signed_form(payload: dict, *, secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    raw = urlencode({"payload": json.dumps(payload, separators=(",", ":"))}).encode()
    ts = str(int(time.time()))
    sig = compute_slack_signature(secret=secret, timestamp=ts, raw_body=raw)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
    }
    return raw, headers


@pytest.fixture()
def slack_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SECRET)
    return SECRET


@pytest.fixture()
def seeded() -> Iterator[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    world = SimDeploymentWorld()
    world.seed("checkout", "bad")
    set_sim_deployment_world(world)
    try:
        yield _seed_awaiting()
    finally:
        set_sim_deployment_world(None)


@pytest.mark.asyncio
async def test_slack_approve_resumes_level2(
    seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    slack_secret: str,
) -> None:
    incident_id, action_id, approval_id = seeded
    task_queue = f"test-k3-approve-{uuid.uuid4().hex[:8]}"
    timers = WorkflowTimerConfig(approval_timeout_seconds=30 * 60)

    value = encode_slack_approval_value(
        approval_id=approval_id,
        action_id=action_id,
        action_version=1,
        decision="APPROVED",
    )
    payload = {
        "type": "block_actions",
        "trigger_id": f"k3-{uuid.uuid4().hex[:10]}",
        "user": {"id": "U_K3"},
        "actions": [{"action_id": "ip_approve", "value": value}],
    }
    raw, headers = _signed_form(payload, secret=slack_secret)

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
                    res = client.post(PATH, content=raw, headers=headers)
                assert res.status_code == 200, res.text
                body = res.json()
                assert body["status"] == "mapped"
                assert body["approval_mapped"] is True
                assert body["workflow_signaled"] is True
                assert "Approved" in body["text"]
                assert body["code"] is None

                result = await handle.result()
                assert result == "MITIGATING"
                assert await handle.query(IncidentWorkflow.approval_wait_result) == "APPROVED"
                assert await handle.query(IncidentWorkflow.remediation_executed) is True
        finally:
            set_temporal_client_override(None)

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, decided_by FROM domain.approval WHERE id = %s",
            (str(approval_id),),
        )
        status, decided_by = cur.fetchone()
        assert status == "APPROVED"
        assert str(decided_by).startswith("slack:")


@pytest.mark.asyncio
async def test_slack_stale_version_visible(
    seeded: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    slack_secret: str,
) -> None:
    _incident_id, action_id, approval_id = seeded
    # Button still claims v1 binding but with wrong action_version=99.
    value = encode_slack_approval_value(
        approval_id=approval_id,
        action_id=action_id,
        action_version=99,
        decision="APPROVED",
    )
    payload = {
        "type": "block_actions",
        "trigger_id": f"k3-stale-{uuid.uuid4().hex[:10]}",
        "user": {"id": "U_STALE"},
        "actions": [{"action_id": "ip_approve", "value": value}],
    }
    raw, headers = _signed_form(payload, secret=slack_secret)

    with TestClient(app) as client:
        res = client.post(PATH, content=raw, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "stale"
    assert body["code"] == STALE_CODE
    assert STALE_CODE in body["text"]
    assert body["approval_mapped"] is False
    assert body["workflow_signaled"] is False

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM domain.approval WHERE id = %s",
            (str(approval_id),),
        )
        assert cur.fetchone()[0] == "PENDING"
        cur.execute(
            """
            SELECT status FROM domain.slack_interaction
            WHERE id = %s
            """,
            (body["interaction_id"],),
        )
        assert cur.fetchone()[0] == "FAILED"
