"""J9: Compensation Action — new Action + fresh policy; no parent approval reuse."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import (
    ParentApprovalReuseDenied,
    PolicyDecisionExists,
    assert_approval_authorizes,
    create_approval_command,
    create_runbook_command,
    create_runbook_version_command,
    decide_approval_command,
    evaluate_policy_command,
    pin_runbook_version_command,
    propose_action_command,
    propose_compensation_action_command,
    publish_runbook_version_command,
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
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'domain'
                      AND table_name = 'action'
                      AND column_name = 'compensates_action_id'
                    """
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def _parent_disable_approved(conn: object):
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DEGRADED', 'j9 compensation', 5)
            """,
            (str(incident_id), f"INC-J9-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"j9.rb.{uuid.uuid4().hex[:8]}",
        title="J9 RB",
        service_key="auth",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# j9",
        allowed_action_types=["DISABLE_FEATURE_FLAG", "RESTORE_FEATURE_FLAG"],
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
    parent = propose_action_command(
        conn,
        incident_id=incident_id,
        action_type="DISABLE_FEATURE_FLAG",
        parameters={"flag": "strict_jwt", "service": "auth"},
        commit=False,
    )
    evaluate_policy_command(
        conn,
        action_id=parent.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    create_approval_command(
        conn,
        action_id=parent.action_id,
        action_version=parent.version,
        commit=False,
    )
    decide_approval_command(
        conn,
        action_id=parent.action_id,
        action_version=parent.version,
        status="APPROVED",
        decided_by="harness:j9",
        commit=False,
    )
    return incident_id, parent


@pytest.mark.skipif(not _db_available(), reason="Postgres/migration 0015 not ready")
def test_compensation_is_new_action_linked_to_parent(conn: object) -> None:
    _incident_id, parent = _parent_disable_approved(conn)
    compensation = propose_compensation_action_command(
        conn,
        parent_action_id=parent.action_id,
        parent_action_version=parent.version,
        parameters={"flag": "strict_jwt", "service": "auth", "value": False},
        commit=False,
    )
    assert compensation.action_id != parent.action_id
    assert compensation.action_type == "RESTORE_FEATURE_FLAG"
    assert compensation.compensates_action_id == parent.action_id
    assert compensation.compensates_action_version == parent.version
    assert compensation.version == 1

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT compensates_action_id, compensates_action_version,
                   provenance->>'inherits_parent_approval'
            FROM domain.action WHERE id = %s
            """,
            (str(compensation.action_id),),
        )
        row = cur.fetchone()
        assert uuid.UUID(str(row[0])) == parent.action_id
        assert int(row[1]) == parent.version
        assert row[2] == "false"


@pytest.mark.skipif(not _db_available(), reason="Postgres/migration 0015 not ready")
def test_compensation_cannot_reuse_parent_approval(conn: object) -> None:
    _incident_id, parent = _parent_disable_approved(conn)
    compensation = propose_compensation_action_command(
        conn,
        parent_action_id=parent.action_id,
        parameters={"flag": "strict_jwt", "service": "auth", "value": False},
        commit=False,
    )
    # Parent approval still valid for parent.
    assert_approval_authorizes(
        conn, action_id=parent.action_id, action_version=parent.version
    )
    # Same approval must not authorize compensation.
    with pytest.raises(ParentApprovalReuseDenied, match="fresh Approval"):
        assert_approval_authorizes(
            conn,
            action_id=compensation.action_id,
            action_version=compensation.version,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres/migration 0015 not ready")
def test_compensation_requires_new_policy_decision(conn: object) -> None:
    _incident_id, parent = _parent_disable_approved(conn)
    compensation = propose_compensation_action_command(
        conn,
        parent_action_id=parent.action_id,
        parameters={"flag": "strict_jwt", "service": "auth", "value": False},
        commit=False,
    )
    # Parent already has a PolicyDecision; compensation must get its own.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM domain.policy_decision
            WHERE action_id = %s
            """,
            (str(compensation.action_id),),
        )
        assert cur.fetchone()[0] == 0

    fresh = evaluate_policy_command(
        conn,
        action_id=compensation.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    assert fresh.action_id == compensation.action_id
    assert fresh.decision == "REQUIRE_APPROVAL"

    # Re-evaluate same compensation version → exists (immutable).
    with pytest.raises(PolicyDecisionExists):
        evaluate_policy_command(
            conn,
            action_id=compensation.action_id,
            action_version=compensation.version,
            autonomy_level=2,
            actor="system",
            commit=False,
        )

    create_approval_command(
        conn,
        action_id=compensation.action_id,
        action_version=compensation.version,
        commit=False,
    )
    decide_approval_command(
        conn,
        action_id=compensation.action_id,
        action_version=compensation.version,
        status="APPROVED",
        decided_by="harness:j9-comp",
        commit=False,
    )
    assert_approval_authorizes(
        conn,
        action_id=compensation.action_id,
        action_version=compensation.version,
    )
