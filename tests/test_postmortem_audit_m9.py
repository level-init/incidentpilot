"""M9: postmortem + audit views; Admin-only AI provenance lineage."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "api",
    ROOT / "shared",
    ROOT / "adapters",
):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402

psycopg = pytest.importorskip("psycopg")

ADMIN = {"Authorization": "Bearer local-dev-admin"}
RESPONDER = {"Authorization": "Bearer local-dev"}
VIEWER = {"Authorization": "Bearer local-dev-viewer"}


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.postmortem LIMIT 1")
                cur.execute("SELECT 1 FROM domain.ai_invocation LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_openapi_m9_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/incidents/{incident_id}/postmortem" in paths
    assert "/incidents/{incident_id}/audit" in paths
    assert "/incidents/{incident_id}/ai-invocations" in paths
    assert "/ai-invocations/{invocation_id}/provenance" in paths
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "AiInvocationSummaryOut" in schemas
    assert "AuditEventOut" in schemas
    assert "PostmortemOut" in schemas


def test_ai_invocations_admin_only(client: TestClient) -> None:
    """Denial must 403 without opening Postgres (unit CI has no DB)."""
    iid = uuid.uuid4()
    for headers in (VIEWER, RESPONDER):
        res = client.get(f"/incidents/{iid}/ai-invocations", headers=headers)
        assert res.status_code == 403, res.text
        denied = client.get(
            f"/ai-invocations/{iid}/provenance",
            headers=headers,
        )
        assert denied.status_code == 403, denied.text


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_viewer_reads_postmortem_and_audit_responder_writes(
    client: TestClient,
) -> None:
    iid = uuid.uuid4()
    public_id = f"INC-M9-{iid.hex[:8]}"

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (
                id, public_id, state, title, incident_revision
            ) VALUES (%s, %s, 'RESOLVED', 'm9 postmortem', 4)
            """,
            (str(iid), public_id),
        )
        cur.execute(
            """
            INSERT INTO domain.evidence (
                id, evidence_key, incident_id, kind, fingerprint,
                summary, payload, provenance, producer, observed_at
            ) VALUES (
                %s, %s, %s, 'METRIC', %s,
                'm9 err rate', '{}'::jsonb, '{}'::jsonb, 'test_producer', now()
            )
            """,
            (
                str(uuid.uuid4()),
                f"EV-m9-{iid.hex[:6]}",
                str(iid),
                f"fp-m9-{iid.hex}",
            ),
        )
        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (
                %s, 'STATE_TRANSITION', 'RECOVERED → RESOLVED', 'system',
                '{"from":"RECOVERED","to":"RESOLVED"}'::jsonb
            )
            """,
            (str(iid),),
        )
        cur.execute(
            """
            INSERT INTO domain.audit_event (
                action, actor, resource_type, resource_id, incident_id,
                outcome, details
            ) VALUES (
                'incident.create', 'user_local_dev', 'incident', %s, %s,
                'success', '{"path":"m9"}'::jsonb
            )
            """,
            (str(iid), str(iid)),
        )
        conn.commit()

    missing = client.get(f"/incidents/{iid}/postmortem", headers=VIEWER)
    assert missing.status_code == 404

    # Viewer cannot draft
    denied = client.post(
        f"/incidents/{iid}/postmortem/draft",
        headers=VIEWER,
        json={},
    )
    assert denied.status_code == 403

    draft = client.post(
        f"/incidents/{iid}/postmortem/draft",
        headers=RESPONDER,
        json={},
    )
    assert draft.status_code == 201, draft.text
    assert draft.json()["status"] == "DRAFT"

    viewed = client.get(f"/incidents/{iid}/postmortem", headers=VIEWER)
    assert viewed.status_code == 200, viewed.text
    assert viewed.json()["status"] == "DRAFT"

    audit = client.get(f"/incidents/{iid}/audit?order=asc", headers=VIEWER)
    assert audit.status_code == 200, audit.text
    actions = [r["action"] for r in audit.json()]
    assert "incident.create" in actions

    finalize = client.post(
        f"/incidents/{iid}/postmortem/finalize",
        headers=RESPONDER,
        json={"corrective_actions": [{"title": "Add canary", "owner": "platform"}]},
    )
    assert finalize.status_code == 200, finalize.text
    assert finalize.json()["status"] == "FINAL"

    # Seed AI invocation; only Admin lists + opens provenance
    inv_id = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.ai_invocation (
                id, incident_id, purpose, provider, model, status,
                request_metadata, response_metadata
            ) VALUES (
                %s, %s, 'diagnose', 'fake', 'test-model', 'succeeded',
                '{"input_evidence_ids":[]}'::jsonb, '{}'::jsonb
            )
            """,
            (str(inv_id), str(iid)),
        )
        conn.commit()

    listed = client.get(f"/incidents/{iid}/ai-invocations", headers=ADMIN)
    assert listed.status_code == 200, listed.text
    assert any(r["invocation_id"] == str(inv_id) for r in listed.json())

    prov = client.get(f"/ai-invocations/{inv_id}/provenance", headers=ADMIN)
    assert prov.status_code == 200, prov.text
    assert prov.json()["invocation_id"] == str(inv_id)
    assert prov.json()["purpose"] == "diagnose"

    for headers in (VIEWER, RESPONDER):
        assert (
            client.get(f"/ai-invocations/{inv_id}/provenance", headers=headers).status_code
            == 403
        )
