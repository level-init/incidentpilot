"""L5: FINAL postmortem + corrective_actions[]; CLOSED only after FINAL."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import (
    PostmortemCorrectiveActionsError,
    PostmortemFinalRequiredError,
    append_evidence_command,
    create_postmortem_draft_command,
    finalize_postmortem_command,
    transition_incident_command,
)
from incidentpilot_shared.domain.transitions import IllegalTransitionError, IncidentState
from incidentpilot_shared.timeline import append_timeline_event

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
                cur.execute("SELECT 1 FROM domain.postmortem LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def _seed_resolved_with_draft(conn: object) -> tuple[uuid.UUID, int]:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'RESOLVED', 'l5 postmortem final', 5)
            """,
            (str(incident_id), f"INC-L5-{uuid.uuid4().hex[:8]}"),
        )
    append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="METRIC",
        fingerprint=f"l5-{uuid.uuid4().hex[:8]}",
        summary="error rate recovered",
        producer="test_producer",
        commit=False,
    )
    append_timeline_event(
        conn,
        incident_id=incident_id,
        event_type="STATE_TRANSITION",
        summary="RECOVERED → RESOLVED",
        actor="system",
    )
    create_postmortem_draft_command(conn, incident_id=incident_id, commit=False)
    return incident_id, 5


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_empty_corrective_actions_rejected(conn: object) -> None:
    incident_id, _rev = _seed_resolved_with_draft(conn)
    with pytest.raises(PostmortemCorrectiveActionsError, match="non-empty"):
        finalize_postmortem_command(
            conn,
            incident_id=incident_id,
            corrective_actions=[],
            commit=False,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_cannot_skip_resolved_to_closed(conn: object) -> None:
    incident_id, rev = _seed_resolved_with_draft(conn)
    with pytest.raises(IllegalTransitionError, match="RESOLVED → CLOSED"):
        transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=rev,
            to_state=IncidentState.CLOSED,
            commit=False,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_closed_requires_final_postmortem(conn: object) -> None:
    incident_id, rev = _seed_resolved_with_draft(conn)
    # Enter POSTMORTEM without FINAL.
    transitioned = transition_incident_command(
        conn,
        incident_id=incident_id,
        expected_revision=rev,
        to_state=IncidentState.POSTMORTEM,
        commit=False,
    )
    with pytest.raises(PostmortemFinalRequiredError, match="FINAL postmortem"):
        transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=transitioned.new_revision,
            to_state=IncidentState.CLOSED,
            commit=False,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_finalize_then_closed(conn: object) -> None:
    incident_id, _rev = _seed_resolved_with_draft(conn)
    with pytest.raises(PostmortemCorrectiveActionsError, match="title"):
        finalize_postmortem_command(
            conn,
            incident_id=incident_id,
            corrective_actions=[{"owner": "platform"}],
            commit=False,
        )

    finalized = finalize_postmortem_command(
        conn,
        incident_id=incident_id,
        corrective_actions=[
            {"title": "Add deploy canary", "owner": "platform"},
            {"title": "Improve rollback runbook"},
        ],
        actor="harness:l5",
        commit=False,
    )
    assert finalized.status == "FINAL"
    assert finalized.incident_state == "POSTMORTEM"
    assert len(finalized.corrective_actions) == 2
    assert finalized.corrective_actions[0]["title"] == "Add deploy canary"

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, finalized_at IS NOT NULL, corrective_actions->0->>'title'
            FROM domain.postmortem WHERE id = %s
            """,
            (str(finalized.postmortem_id),),
        )
        status, has_finalized, title = cur.fetchone()
    assert status == "FINAL"
    assert has_finalized is True
    assert title == "Add deploy canary"

    closed = transition_incident_command(
        conn,
        incident_id=incident_id,
        expected_revision=finalized.incident_revision,
        to_state=IncidentState.CLOSED,
        commit=False,
    )
    assert closed.to_state == IncidentState.CLOSED
