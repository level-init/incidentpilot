"""L2: AuditEvent for privileged ops — approve/execute writers + query shape."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_adapters.remediation import SimDeploymentWorld, SimRollbackAdapter
from incidentpilot_remediation.execute import verify_reconcile_and_execute
from incidentpilot_shared.audit import AUDIT_ACTIONS, list_audit_actions
from incidentpilot_shared.domain.commands import (
    create_approval_command,
    create_runbook_command,
    create_runbook_version_command,
    decide_approval_command,
    evaluate_policy_command,
    pin_runbook_version_command,
    propose_action_command,
    publish_runbook_version_command,
    reserve_execution_attempt_command,
    upsert_autonomy_config_command,
)

psycopg = pytest.importorskip("psycopg")


def _dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "incidentpilot")
    password = os.environ.get("IP_APP_PASSWORD", "incidentpilot_app")
    return f"postgresql://ip_app:{password}@{host}:{port}/{db}"


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.audit_event LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def _approved_rollback(conn: object):
    params = {"revision": "prev", "deployment": "checkout"}
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'l2 audit', 3)
            """,
            (str(incident_id), f"INC-L2-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"l2.rb.{uuid.uuid4().hex[:8]}",
        title="L2 RB",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# l2",
        allowed_action_types=["ROLLBACK_DEPLOYMENT"],
        commit=False,
    )
    published = publish_runbook_version_command(
        conn, runbook_version_id=ver.runbook_version_id, commit=False
    )
    pin_runbook_version_command(
        conn,
        incident_id=incident_id,
        runbook_version_id=published.runbook_version_id,
        commit=False,
    )
    proposed = propose_action_command(
        conn,
        incident_id=incident_id,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters=params,
        commit=False,
    )
    evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    create_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        commit=False,
    )
    return incident_id, proposed, params


def test_catalog_includes_approve_and_execute() -> None:
    assert "approval.decide" in AUDIT_ACTIONS
    assert "remediation.execute" in AUDIT_ACTIONS


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_approve_and_execute_create_audit_events(conn: object) -> None:
    """L2 AC: Approve/execute create AuditEvents."""
    incident_id, proposed, params = _approved_rollback(conn)
    decide_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        status="APPROVED",
        decided_by="harness:l2",
        commit=False,
    )
    attempt = reserve_execution_attempt_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        commit=False,
    )
    world = SimDeploymentWorld()
    world.seed("checkout", "bad")
    adapter = SimRollbackAdapter(world)
    verified, result = verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="ROLLBACK_DEPLOYMENT",
    )
    assert result.ok is True
    assert verified.incident_id == incident_id

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT action, actor, resource_type, outcome, details
            FROM domain.audit_event
            WHERE incident_id = %s
              AND action IN ('approval.decide', 'remediation.execute')
            ORDER BY occurred_at ASC, created_at ASC
            """,
            (str(incident_id),),
        )
        rows = cur.fetchall()
    assert len(rows) == 2
    approve_action, approve_actor, approve_rtype, approve_outcome, approve_details = rows[0]
    assert approve_action == "approval.decide"
    assert approve_actor == "harness:l2"
    assert approve_rtype == "approval"
    assert approve_outcome == "success"
    assert approve_details["status"] == "APPROVED"

    exec_action, exec_actor, exec_rtype, exec_outcome, exec_details = rows[1]
    assert exec_action == "remediation.execute"
    assert exec_actor == "system"
    assert exec_rtype == "execution_attempt"
    assert exec_outcome == "success"
    assert exec_details["ok"] is True
    assert exec_details["attempt_id"] == str(attempt.attempt_id)

    actions = list_audit_actions(conn, incident_id=incident_id)
    assert "approval.decide" in actions
    assert "remediation.execute" in actions
    assert "policy.evaluate" in actions


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_admin_autonomy_upsert_audited(conn: object) -> None:
    upsert_autonomy_config_command(
        conn,
        autonomy_level=2,
        service_key=f"l2-svc-{uuid.uuid4().hex[:6]}",
        actor="user_local_admin",
        commit=False,
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT action, actor, resource_type, outcome
            FROM domain.audit_event
            WHERE action = 'admin.autonomy_upsert'
              AND actor = 'user_local_admin'
            ORDER BY occurred_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "admin.autonomy_upsert"
    assert row[2] == "autonomy_config"
    assert row[3] == "success"
