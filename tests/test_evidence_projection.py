"""G2: redaction wired into Evidence projections; secrets never reach LLM read."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))

from incidentpilot_shared.domain.commands import append_evidence_command  # noqa: E402
from incidentpilot_shared.evidence_projections import (  # noqa: E402
    persist_evidence_projection,
    read_evidence_projection_for_llm,
)
from incidentpilot_shared.redaction import RedactionError  # noqa: E402

psycopg = pytest.importorskip("psycopg")

PLANTED_SECRET = "AKIAIOSFODNN7EXAMPLE"


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.evidence_projection LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="Postgres/migration not ready")


def _incident() -> uuid.UUID:
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'G2 projection', 1)
            """,
            (str(iid), f"INC-G2-{iid.hex[:8]}"),
        )
        conn.commit()
    return iid


def test_planted_secret_absent_from_projection_canonical_unchanged() -> None:
    iid = _incident()
    payload = {
        "log": f"auth failed key={PLANTED_SECRET} user=oncall@example.com",
        "meta": {"note": "keep"},
    }
    with psycopg.connect(_dsn()) as conn:
        result = append_evidence_command(
            conn,
            incident_id=iid,
            kind="LOG",
            fingerprint=f"prometheus_collector:g2-{uuid.uuid4().hex}",
            summary=f"spike password=hunter2password {PLANTED_SECRET}",
            producer="prometheus_collector",
            payload=payload,
            commit=True,
        )
        projection = read_evidence_projection_for_llm(
            conn, incident_id=iid, evidence_id=result.evidence_id
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload, summary FROM domain.evidence WHERE id = %s",
                (str(result.evidence_id),),
            )
            canonical_payload, canonical_summary = cur.fetchone()
            cur.execute(
                "SELECT status FROM domain.evidence_projection WHERE evidence_id = %s",
                (str(result.evidence_id),),
            )
            assert cur.fetchone()[0] == "READY"

    blob = projection.summary + str(projection.structured_data)
    assert PLANTED_SECRET not in blob
    assert "hunter2password" not in blob
    assert "oncall@example.com" not in blob
    assert "[REDACTED:" in blob

    # Canonical Evidence unchanged (planted secret still present for audit).
    assert PLANTED_SECRET in str(canonical_payload)
    assert PLANTED_SECRET in str(canonical_summary)
    assert canonical_payload["meta"]["note"] == "keep"


def test_blocked_projection_never_reaches_llm_read() -> None:
    """Unsupported payload types → BLOCKED projection; LLM read fails closed."""
    iid = _incident()
    eid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.evidence (
                id, evidence_key, incident_id, kind, fingerprint,
                summary, payload, producer, observed_at
            ) VALUES (
                %s, %s, %s, 'LOG', %s,
                'raw', %s::jsonb, 'loki_collector', now()
            )
            """,
            (
                str(eid),
                f"EV-{eid.hex[:12]}",
                str(iid),
                f"loki_collector:block-{eid.hex}",
                f'{{"note":"canonical-secret-{PLANTED_SECRET}"}}',
            ),
        )
        ref = persist_evidence_projection(
            conn,
            evidence_id=eid,
            summary="ok",
            payload={"blob": b"\x00secret-bytes"},
        )
        assert ref.status == "BLOCKED"
        conn.commit()

        with pytest.raises(RedactionError, match="blocked"):
            read_evidence_projection_for_llm(conn, incident_id=iid, evidence_id=eid)

        cur.execute("SELECT payload FROM domain.evidence WHERE id = %s", (str(eid),))
        canonical = cur.fetchone()[0]
        assert PLANTED_SECRET in str(canonical)


def test_missing_projection_fails_closed() -> None:
    iid = _incident()
    with psycopg.connect(_dsn()) as conn, pytest.raises(RedactionError, match="no evidence"):
        read_evidence_projection_for_llm(conn, incident_id=iid, evidence_id=uuid.uuid4())
