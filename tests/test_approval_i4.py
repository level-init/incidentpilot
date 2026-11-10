"""I4: Approval create/consume — version-bound, single-use, stale reject."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import (
    StaleActionVersion,
    assert_approval_authorizes,
    consume_approval_command,
    create_approval_command,
    create_runbook_command,
    create_runbook_version_command,
    decide_approval_command,
    evaluate_policy_command,
    pin_runbook_version_command,
    propose_action_command,
    publish_runbook_version_command,
)
from incidentpilot_shared.processors.policy import assert_approval_satisfied

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
                cur.execute("SELECT 1 FROM domain.approval LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def _propose_rollback(conn: object):
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DIAGNOSED', 'i4 approval', 2)
            """,
            (str(incident_id), f"INC-I4-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"i4.rb.{uuid.uuid4().hex[:8]}",
        title="I4 RB",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# i4",
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
    return propose_action_command(
        conn,
        incident_id=incident_id,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters={"revision": "prev"},
        commit=False,
    )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_evaluate_creates_pending_approval(conn: object) -> None:
    proposed = _propose_rollback(conn)
    result = evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    assert result.decision == "REQUIRE_APPROVAL"
    assert result.action_status == "AWAITING_APPROVAL"

    created = create_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        commit=False,
    )
    assert created.inserted is False
    assert created.status == "PENDING"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_duplicate_approve_safe(conn: object) -> None:
    proposed = _propose_rollback(conn)
    evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    first = decide_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        status="APPROVED",
        decided_by="responder",
        commit=False,
    )
    assert first.noop is False
    assert first.status == "APPROVED"
    assert first.action_status == "APPROVED"

    second = decide_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        status="APPROVED",
        decided_by="responder",
        commit=False,
    )
    assert second.noop is True
    assert second.approval_id == first.approval_id


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_reject_is_visible(conn: object) -> None:
    proposed = _propose_rollback(conn)
    evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    decided = decide_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        status="REJECTED",
        decided_by="responder",
        commit=False,
    )
    assert decided.status == "REJECTED"
    assert decided.action_status == "CANCELLED"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM domain.approval WHERE id = %s",
            (str(decided.approval_id),),
        )
        assert cur.fetchone()[0] == "REJECTED"
        cur.execute(
            "SELECT status FROM domain.action WHERE id = %s",
            (str(proposed.action_id),),
        )
        assert cur.fetchone()[0] == "CANCELLED"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_v2_approval_cannot_authorize_v3(conn: object) -> None:
    proposed = _propose_rollback(conn)
    evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    decide_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=1,
        status="APPROVED",
        decided_by="responder",
        commit=False,
    )
    assert_approval_authorizes(conn, action_id=proposed.action_id, action_version=1)

    # Param change → immutable v2 (current_version becomes 2).
    bumped = propose_action_command(
        conn,
        incident_id=proposed.incident_id,
        action_id=proposed.action_id,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters={"revision": "older"},
        commit=False,
    )
    assert bumped.version == 2
    assert bumped.bumped is True

    with pytest.raises(StaleActionVersion, match="STALE_ACTION_VERSION"):
        assert_approval_authorizes(conn, action_id=proposed.action_id, action_version=2)
    with pytest.raises(StaleActionVersion, match="STALE_ACTION_VERSION"):
        consume_approval_command(
            conn,
            action_id=proposed.action_id,
            action_version=2,
            commit=False,
        )

    # v1 approval still consumable for v1 only.
    consumed = consume_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=1,
        commit=False,
    )
    assert consumed.status == "CONSUMED"
    assert consumed.noop is False
    again = consume_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=1,
        commit=False,
    )
    assert again.noop is True


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_single_use_consume_and_policy_gate(conn: object) -> None:
    proposed = _propose_rollback(conn)
    evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    decide_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=1,
        status="APPROVED",
        decided_by="harness",
        commit=False,
    )
    assert_approval_satisfied("REQUIRE_APPROVAL", approval_status="APPROVED")
    with pytest.raises(PermissionError, match="Approval"):
        assert_approval_satisfied("REQUIRE_APPROVAL", approval_status="PENDING")

    consume_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=1,
        commit=False,
    )
    assert_approval_satisfied("REQUIRE_APPROVAL", approval_status="CONSUMED")
    assert_approval_authorizes(conn, action_id=proposed.action_id, action_version=1)
