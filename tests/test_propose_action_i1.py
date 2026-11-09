"""I1: ProposeAction + immutable action_version (runbook-constrained)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import (
    ActionTypeNotAllowed,
    PinnedRunbookRequired,
    create_runbook_command,
    create_runbook_version_command,
    pin_runbook_version_command,
    propose_action_command,
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
                cur.execute("SELECT 1 FROM domain.action_version LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def _incident_with_pin(conn: object) -> tuple[uuid.UUID, uuid.UUID]:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DIAGNOSED', 'i1 propose', 2)
            """,
            (str(incident_id), f"INC-I1-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"i1.rb.{uuid.uuid4().hex[:8]}",
        title="I1 RB",
        hypothesis_class="high_error_rate",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# prose may mention SCALE but allowlist wins",
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
    return incident_id, published.runbook_version_id


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_rollback_proposal_for_seeded_allowlist(conn: object) -> None:
    incident_id, pinned = _incident_with_pin(conn)
    result = propose_action_command(
        conn,
        incident_id=incident_id,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters={"revision": "prev"},
        commit=False,
    )
    assert result.version == 1
    assert result.bumped is False
    assert result.action_type == "ROLLBACK_DEPLOYMENT"
    assert result.runbook_version_id == pinned
    assert result.allowed_action_types == ("ROLLBACK_DEPLOYMENT",)
    assert result.is_reversible is True

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT version, parameters
            FROM domain.action_version WHERE action_id = %s
            """,
            (str(result.action_id),),
        )
        version, parameters = cur.fetchone()
    assert version == 1
    assert parameters["revision"] == "prev"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_invalid_type_rejected(conn: object) -> None:
    incident_id, _ = _incident_with_pin(conn)
    with pytest.raises(ActionTypeNotAllowed, match="SCALE_WORKLOAD"):
        propose_action_command(
            conn,
            incident_id=incident_id,
            action_type="SCALE_WORKLOAD",
            parameters={"replicas": 5},
            commit=False,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_param_change_bumps_immutable_version(conn: object) -> None:
    incident_id, _ = _incident_with_pin(conn)
    first = propose_action_command(
        conn,
        incident_id=incident_id,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters={"revision": "v1"},
        commit=False,
    )
    same = propose_action_command(
        conn,
        incident_id=incident_id,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters={"revision": "v1"},
        action_id=first.action_id,
        commit=False,
    )
    assert same.bumped is False
    assert same.version == 1

    bumped = propose_action_command(
        conn,
        incident_id=incident_id,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters={"revision": "v2"},
        action_id=first.action_id,
        commit=False,
    )
    assert bumped.bumped is True
    assert bumped.version == 2
    assert bumped.current_version == 2

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*), max(version)
            FROM domain.action_version WHERE action_id = %s
            """,
            (str(first.action_id),),
        )
        count, max_v = cur.fetchone()
        assert count == 2
        assert max_v == 2
        with pytest.raises(Exception, match="immutable"):
            cur.execute(
                """
                UPDATE domain.action_version
                SET parameters = '{}'::jsonb
                WHERE action_id = %s AND version = 1
                """,
                (str(first.action_id),),
            )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_requires_pinned_runbook(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DIAGNOSED', 'i1 no pin', 1)
            """,
            (str(incident_id), f"INC-I1N-{uuid.uuid4().hex[:8]}"),
        )
    with pytest.raises(PinnedRunbookRequired):
        propose_action_command(
            conn,
            incident_id=incident_id,
            action_type="ROLLBACK_DEPLOYMENT",
            commit=False,
        )
