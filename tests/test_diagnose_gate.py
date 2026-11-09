"""H5: SYSTEM LEADING + DIAGNOSED gate; AI cannot transition."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.ai_tools import (
    AI_SANDBOX_IDENTITY,
    DENIED_TOOL_NAMES,
    default_ai_tool_registry,
)
from incidentpilot_shared.domain.commands import (
    DiagnoseActorDenied,
    DiagnosedGateError,
    append_evidence_command,
    diagnose_incident_command,
    propose_hypothesis_command,
    transition_incident_command,
)
from incidentpilot_shared.domain.transitions import IncidentState

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


def _seed_investigating(conn: object) -> tuple[uuid.UUID, uuid.UUID, int]:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'h5 diagnose', 2)
            """,
            (str(incident_id), f"INC-H5-{uuid.uuid4().hex[:8]}"),
        )
    ev = append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="LOG",
        fingerprint=f"fp-{uuid.uuid4().hex}",
        summary="signal",
        producer="test_producer",
        commit=False,
    )
    hypo = propose_hypothesis_command(
        conn,
        incident_id=incident_id,
        statement="bad deploy",
        cited_evidence_ids=[ev.evidence_key],
        heuristic_score=0.8,
        commit=False,
    )
    return incident_id, hypo.hypothesis_id, 2


def test_diagnose_tools_denied_to_ai_sandbox() -> None:
    registry = default_ai_tool_registry()
    for name in (
        "diagnose_incident",
        "transition_incident",
        "mark_leading",
        "hypothesis_leading",
        "apply_diagnosed_gate",
        "incident_transition",
    ):
        assert name in DENIED_TOOL_NAMES
        assert registry.is_allowed(name) is False


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_diagnosed_requires_system_gate(conn: object) -> None:
    incident_id, _hid, rev = _seed_investigating(conn)
    with pytest.raises(DiagnosedGateError, match="diagnose_incident_command"):
        transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=rev,
            to_state=IncidentState.DIAGNOSED,
            commit=False,
        )
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM domain.incident WHERE id = %s", (str(incident_id),))
        assert cur.fetchone()[0] == "INVESTIGATING"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_ai_cannot_diagnose(conn: object) -> None:
    incident_id, hid, rev = _seed_investigating(conn)
    with pytest.raises(DiagnoseActorDenied, match="SYSTEM gate"):
        diagnose_incident_command(
            conn,
            incident_id=incident_id,
            hypothesis_id=hid,
            expected_revision=rev,
            actor=AI_SANDBOX_IDENTITY,
            commit=False,
        )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        assert cur.fetchone()[0] == "INVESTIGATING"
        cur.execute(
            "SELECT status, leading_at FROM domain.hypothesis WHERE id = %s",
            (str(hid),),
        )
        status, leading_at = cur.fetchone()
    assert status == "PROPOSED"
    assert leading_at is None


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_system_diagnose_sets_leading_and_diagnosed(conn: object) -> None:
    incident_id, hid, rev = _seed_investigating(conn)
    result = diagnose_incident_command(
        conn,
        incident_id=incident_id,
        hypothesis_id=hid,
        expected_revision=rev,
        actor="system",
        commit=False,
    )
    assert result.to_state == "DIAGNOSED"
    assert result.new_revision == rev + 1
    assert result.leading_at is not None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state, incident_revision FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        state, revision = cur.fetchone()
        cur.execute(
            "SELECT status, leading_at IS NOT NULL FROM domain.hypothesis WHERE id = %s",
            (str(hid),),
        )
        hypo_status, has_leading = cur.fetchone()
    assert state == "DIAGNOSED"
    assert revision == rev + 1
    assert hypo_status == "LEADING"
    assert has_leading is True


def test_apply_diagnosed_gate_activity_registered() -> None:
    from pathlib import Path

    from incidentpilot_worker.activities import apply_diagnosed_gate

    assert callable(apply_diagnosed_gate)
    factory = (
        Path(__file__).resolve().parents[1]
        / "worker"
        / "incidentpilot_worker"
        / "worker_factory.py"
    ).read_text(encoding="utf-8")
    assert "apply_diagnosed_gate" in factory
