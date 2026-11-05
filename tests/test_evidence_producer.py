"""G1: EvidenceProducer write API + fingerprint dedup."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "api", ROOT / "shared", ROOT / "worker"):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402
from incidentpilot_shared.ai_tools import (  # noqa: E402
    AI_SANDBOX_IDENTITY,
    DENIED_TOOL_NAMES,
    ToolDeniedError,
    default_ai_tool_registry,
)
from incidentpilot_shared.domain.commands import append_evidence_command  # noqa: E402
from incidentpilot_shared.evidence_producers import (  # noqa: E402
    EvidenceProducerDenied,
    assert_registered_evidence_producer,
    is_registered_evidence_producer,
)

psycopg = pytest.importorskip("psycopg")


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.evidence LIMIT 1")
            return True
    except Exception:
        return False


def _insert_incident() -> uuid.UUID:
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'G1 evidence', 1)
            """,
            (str(iid), f"INC-G1-{iid.hex[:8]}"),
        )
        conn.commit()
    return iid


def test_ai_sandbox_is_not_registered_producer() -> None:
    assert not is_registered_evidence_producer(AI_SANDBOX_IDENTITY)
    assert not is_registered_evidence_producer("ai_broker")
    with pytest.raises(EvidenceProducerDenied):
        assert_registered_evidence_producer(AI_SANDBOX_IDENTITY)


def test_ai_cannot_call_evidence_write_tools() -> None:
    registry = default_ai_tool_registry()
    for name in (
        "evidence_write",
        "evidence_append",
        "append_evidence",
        "produce_evidence",
    ):
        assert name in DENIED_TOOL_NAMES
        assert registry.is_allowed(name) is False
        with pytest.raises(ToolDeniedError):
            registry.require_allowed(name)


def test_registered_collectors_and_session() -> None:
    assert is_registered_evidence_producer("prometheus_collector")
    assert is_registered_evidence_producer("session:user_local_dev")
    assert not is_registered_evidence_producer("session:")
    assert not is_registered_evidence_producer("unknown_bot")


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_duplicate_scrape_idempotent() -> None:
    iid = _insert_incident()
    fp = f"prometheus_collector:scrape-{uuid.uuid4().hex}"
    with psycopg.connect(_dsn()) as conn:
        first = append_evidence_command(
            conn,
            incident_id=iid,
            kind="METRIC",
            fingerprint=fp,
            summary="error rate",
            producer="prometheus_collector",
            commit=True,
        )
    with psycopg.connect(_dsn()) as conn:
        second = append_evidence_command(
            conn,
            incident_id=iid,
            kind="METRIC",
            fingerprint=fp,
            summary="error rate again",
            producer="prometheus_collector",
            commit=True,
        )
    assert first.inserted is True
    assert second.inserted is False
    assert first.evidence_id == second.evidence_id
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM domain.evidence WHERE incident_id = %s AND fingerprint = %s",
            (str(iid), fp),
        )
        assert cur.fetchone()[0] == 1


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_independent_sources_separate_rows() -> None:
    iid = _insert_incident()
    signal = f"top-errors-{uuid.uuid4().hex[:8]}"
    with psycopg.connect(_dsn()) as conn:
        a = append_evidence_command(
            conn,
            incident_id=iid,
            kind="METRIC",
            fingerprint=f"prometheus_collector:{signal}",
            summary="from prom",
            producer="prometheus_collector",
            commit=False,
        )
        b = append_evidence_command(
            conn,
            incident_id=iid,
            kind="LOG",
            fingerprint=f"loki_collector:{signal}",
            summary="from loki",
            producer="loki_collector",
            commit=False,
        )
        conn.commit()
    assert a.evidence_id != b.evidence_id
    assert a.inserted and b.inserted


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_ai_producer_rejected_at_command() -> None:
    iid = _insert_incident()
    with psycopg.connect(_dsn()) as conn, pytest.raises(EvidenceProducerDenied):
        append_evidence_command(
            conn,
            incident_id=iid,
            kind="LOG",
            fingerprint=f"ai:{uuid.uuid4().hex}",
            summary="should fail",
            producer=AI_SANDBOX_IDENTITY,
            commit=False,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_http_produce_and_dedup() -> None:
    iid = _insert_incident()
    client = TestClient(app)
    headers = {
        "Authorization": "Bearer producer:prometheus_collector",
        "content-type": "application/json",
    }
    body = {
        "kind": "METRIC",
        "fingerprint": f"http-{uuid.uuid4().hex}",
        "summary": "p95 latency",
        "payload": {"p95": 0.42},
    }
    first = client.post(f"/incidents/{iid}/evidence", headers=headers, json=body)
    second = client.post(f"/incidents/{iid}/evidence", headers=headers, json=body)
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["producer"] == "prometheus_collector"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_http_rejects_ai_and_spoofed_producer() -> None:
    iid = _insert_incident()
    client = TestClient(app)
    res = client.post(
        f"/incidents/{iid}/evidence",
        headers={"Authorization": f"Bearer producer:{AI_SANDBOX_IDENTITY}"},
        json={"kind": "LOG", "fingerprint": "x", "summary": "nope"},
    )
    assert res.status_code == 403

    spoof = client.post(
        f"/incidents/{iid}/evidence",
        headers={"Authorization": "Bearer producer:prometheus_collector"},
        json={
            "kind": "LOG",
            "fingerprint": "y",
            "summary": "nope",
            "producer": "ai_sandbox",
        },
    )
    assert spoof.status_code == 400
    assert "producer" in spoof.json()["detail"]


def test_openapi_includes_produce_path() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/incidents/{incident_id}/evidence" in paths
