"""H4: Hypothesis propose/rank — SYSTEM writes; citations required; heuristic scores."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import (
    MissingEvidenceCitationError,
    append_evidence_command,
    propose_hypothesis_command,
    rank_hypotheses_command,
)
from incidentpilot_shared.hypotheses import heuristic_score_from_signals

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
                cur.execute("SELECT 1 FROM domain.hypothesis LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def _insert_incident(conn: object) -> uuid.UUID:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'h4 hypo', 1)
            """,
            (str(incident_id), f"INC-H4-{uuid.uuid4().hex[:8]}"),
        )
    return incident_id


def _append_ev(conn: object, incident_id: uuid.UUID, *, kind: str = "LOG") -> str:
    result = append_evidence_command(
        conn,
        incident_id=incident_id,
        kind=kind,
        fingerprint=f"fp-{uuid.uuid4().hex}",
        summary="sample",
        payload={"ok": True},
        producer="test_producer",
        commit=False,
    )
    return result.evidence_key


def test_heuristic_score_helper_is_clamped() -> None:
    assert 0.0 <= heuristic_score_from_signals(citation_count=0) <= 1.0
    assert heuristic_score_from_signals(citation_count=3, has_change_cite=True) > (
        heuristic_score_from_signals(citation_count=1)
    )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_propose_writes_proposed_with_heuristic_label(conn: object) -> None:
    incident_id = _insert_incident(conn)
    ev_key = _append_ev(conn, incident_id)
    result = propose_hypothesis_command(
        conn,
        incident_id=incident_id,
        statement="bad deploy on payment",
        cited_evidence_ids=[ev_key],
        heuristic_score=0.72,
        proposed_by="AI",
        commit=False,
    )
    assert result.status == "PROPOSED"
    assert result.proposed_by == "AI"
    assert result.heuristic_score == pytest.approx(0.72)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, proposed_by, confidence, provenance, cited_evidence_ids
            FROM domain.hypothesis WHERE id = %s
            """,
            (str(result.hypothesis_id),),
        )
        status, proposed_by, confidence, provenance, cited = cur.fetchone()
    assert status == "PROPOSED"
    assert proposed_by == "AI"
    assert float(confidence) == pytest.approx(0.72)
    meta = provenance if isinstance(provenance, dict) else json.loads(provenance)
    assert meta["score_kind"] == "heuristic"
    assert meta["writer"] == "system"
    assert meta["heuristic_score"] == pytest.approx(0.72)
    assert len(cited) == 1


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_missing_ev_citation_rejected(conn: object) -> None:
    incident_id = _insert_incident(conn)
    with pytest.raises(MissingEvidenceCitationError, match="missing/unknown"):
        propose_hypothesis_command(
            conn,
            incident_id=incident_id,
            statement="invented cite",
            cited_evidence_ids=["EV-not-real-0000"],
            heuristic_score=0.9,
            commit=False,
        )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM domain.hypothesis WHERE incident_id = %s",
            (str(incident_id),),
        )
        assert cur.fetchone()[0] == 0


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_empty_citations_rejected(conn: object) -> None:
    incident_id = _insert_incident(conn)
    with pytest.raises(MissingEvidenceCitationError, match="at least one"):
        propose_hypothesis_command(
            conn,
            incident_id=incident_id,
            statement="no cites",
            cited_evidence_ids=[],
            commit=False,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_multiple_proposed_allowed(conn: object) -> None:
    incident_id = _insert_incident(conn)
    ev_a = _append_ev(conn, incident_id)
    ev_b = _append_ev(conn, incident_id, kind="CHANGE")
    a = propose_hypothesis_command(
        conn,
        incident_id=incident_id,
        statement="hypothesis A",
        cited_evidence_ids=[ev_a],
        heuristic_score=0.4,
        commit=False,
    )
    b = propose_hypothesis_command(
        conn,
        incident_id=incident_id,
        statement="hypothesis B",
        cited_evidence_ids=[ev_b],
        heuristic_score=0.8,
        commit=False,
    )
    assert a.hypothesis_id != b.hypothesis_id
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM domain.hypothesis
            WHERE incident_id = %s AND status = 'PROPOSED'
            """,
            (str(incident_id),),
        )
        assert cur.fetchone()[0] == 2


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_rank_assigns_heuristic_order(conn: object) -> None:
    incident_id = _insert_incident(conn)
    ev = _append_ev(conn, incident_id)
    low = propose_hypothesis_command(
        conn,
        incident_id=incident_id,
        statement="low",
        cited_evidence_ids=[ev],
        heuristic_score=0.2,
        commit=False,
    )
    high = propose_hypothesis_command(
        conn,
        incident_id=incident_id,
        statement="high",
        cited_evidence_ids=[ev],
        heuristic_score=0.9,
        commit=False,
    )
    ranked = rank_hypotheses_command(
        conn,
        incident_id=incident_id,
        rankings=[
            (low.hypothesis_id, 0.2),
            (high.hypothesis_id, 0.9),
        ],
        commit=False,
    )
    assert ranked.ranked[0].hypothesis_id == high.hypothesis_id
    assert ranked.ranked[0].rank == 1
    assert ranked.ranked[1].hypothesis_id == low.hypothesis_id
    assert ranked.ranked[1].rank == 2
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, provenance->>'score_kind'
            FROM domain.hypothesis WHERE id = %s
            """,
            (str(high.hypothesis_id),),
        )
        status, score_kind = cur.fetchone()
    assert status == "PROPOSED"
    assert score_kind == "heuristic"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_cross_incident_citation_rejected(conn: object) -> None:
    a = _insert_incident(conn)
    b = _insert_incident(conn)
    ev_on_b = _append_ev(conn, b)
    with pytest.raises(MissingEvidenceCitationError):
        propose_hypothesis_command(
            conn,
            incident_id=a,
            statement="wrong incident cite",
            cited_evidence_ids=[ev_on_b],
            commit=False,
        )
