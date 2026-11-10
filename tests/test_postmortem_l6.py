"""L6: Postmortem export package — timeline, evidence refs, postmortem body."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_adapters.blob import MemoryBlobStore
from incidentpilot_shared.domain.commands import (
    append_evidence_command,
    create_postmortem_draft_command,
    export_postmortem_package_command,
    finalize_postmortem_command,
)
from incidentpilot_shared.postmortem_export import EXPORT_SCHEMA
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


def _seed_final(conn: object) -> uuid.UUID:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'RESOLVED', 'l6 export', 4)
            """,
            (str(incident_id), f"INC-L6-{uuid.uuid4().hex[:8]}"),
        )
    append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="METRIC",
        fingerprint=f"l6-{uuid.uuid4().hex[:8]}",
        summary="checkout recovered",
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
    finalize_postmortem_command(
        conn,
        incident_id=incident_id,
        corrective_actions=[{"title": "Add canary", "owner": "platform"}],
        commit=False,
    )
    return incident_id


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_export_requires_final(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'RESOLVED', 'l6 draft only', 2)
            """,
            (str(incident_id), f"INC-L6-{uuid.uuid4().hex[:8]}"),
        )
    append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="METRIC",
        fingerprint=f"l6d-{uuid.uuid4().hex[:8]}",
        summary="x",
        producer="test_producer",
        commit=False,
    )
    create_postmortem_draft_command(conn, incident_id=incident_id, commit=False)
    with pytest.raises(ValueError, match="FINAL"):
        export_postmortem_package_command(conn, incident_id=incident_id, commit=False)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_export_contains_timeline_evidence_refs_and_body(conn: object) -> None:
    incident_id = _seed_final(conn)
    store = MemoryBlobStore(bucket="incidentpilot-postmortem-exports")
    result = export_postmortem_package_command(
        conn,
        incident_id=incident_id,
        blob_store=store,
        commit=False,
    )
    pkg = result.package
    assert pkg["schema"] == EXPORT_SCHEMA
    assert pkg["postmortem"]["status"] == "FINAL"
    assert "Grounded claims" in pkg["postmortem"]["body_markdown"]
    assert pkg["postmortem"]["corrective_actions"][0]["title"] == "Add canary"
    assert len(pkg["timeline"]) >= 1
    assert any(e["event_type"] == "STATE_TRANSITION" for e in pkg["timeline"])
    assert len(pkg["evidence_refs"]) >= 1
    assert pkg["evidence_refs"][0]["summary"] == "checkout recovered"
    assert result.export_uri is not None
    assert result.blob_status == "UPLOADED"
    assert result.export_uri in store.objects
    archived = json.loads(store.objects[result.export_uri].decode("utf-8"))
    assert archived["postmortem"]["body_markdown"] == pkg["postmortem"]["body_markdown"]
    assert "timeline" in archived
    assert "evidence_refs" in archived
