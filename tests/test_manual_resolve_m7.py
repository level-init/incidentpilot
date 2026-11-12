"""M7: contextual manual resolve — RECOVERED only, reason + audit, no generic Resolve."""

from __future__ import annotations

import json
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


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.incident LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_openapi_m7_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/incidents/{incident_id}/resolve-context" in paths
    assert "/incidents/{incident_id}/resolve" in paths
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "ResolveContextOut" in schemas
    assert "ManualResolveBody" in schemas
    assert "eligible" in schemas["ResolveContextOut"]["properties"]
    assert "reason" in schemas["ManualResolveBody"]["properties"]


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_resolve_context_hidden_until_recovered(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}
    create = client.post(
        "/incidents",
        headers=headers,
        json={
            "title": "m7 not recovered",
            "severity": "SEV2",
            "service_key": f"checkout-m7-{uuid.uuid4().hex[:6]}",
        },
    )
    assert create.status_code == 201, create.text
    iid = create.json()["id"]
    state = create.json()["state"]
    assert state != "RECOVERED"

    ctx = client.get(f"/incidents/{iid}/resolve-context", headers=headers)
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    assert body["eligible"] is False
    assert body["current_state"] == state
    assert body["reason_required"] is True
    assert "generic" in body["message"].lower() or "RECOVERED" in body["message"]

    denied = client.post(
        f"/incidents/{iid}/resolve",
        headers=headers,
        json={"reason": "should fail", "expected_revision": body["incident_revision"]},
    )
    assert denied.status_code == 409, denied.text
    assert "RECOVERED" in denied.text


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_manual_resolve_recovered_reason_and_audit(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}
    iid = uuid.uuid4()
    public_id = f"INC-M7-{iid.hex[:8]}"
    reason = "health stable; closing after RECOVERED validation"

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (
                id, public_id, state, title, incident_revision
            ) VALUES (%s, %s, 'RECOVERED', 'm7 resolve', 3)
            """,
            (str(iid), public_id),
        )
        cur.execute(
            """
            INSERT INTO domain.validation_result (
                incident_id, outcome, criteria, observations
            ) VALUES (
                %s, 'RECOVERED',
                '{"error_rate_max": 0.05}'::jsonb,
                '{"error_rate": 0.01}'::jsonb
            )
            """,
            (str(iid),),
        )
        conn.commit()

    ctx = client.get(f"/incidents/{iid}/resolve-context", headers=headers)
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    assert body["eligible"] is True
    assert body["current_state"] == "RECOVERED"
    assert body["incident_revision"] == 3
    assert body["health"] is not None
    assert body["health"]["outcome"] == "RECOVERED"
    assert body["health"]["observations"]["error_rate"] == 0.01

    empty = client.post(
        f"/incidents/{iid}/resolve",
        headers=headers,
        json={"reason": "   ", "expected_revision": 3},
    )
    assert empty.status_code == 409, empty.text

    resolved = client.post(
        f"/incidents/{iid}/resolve",
        headers=headers,
        json={"reason": reason, "expected_revision": 3},
    )
    assert resolved.status_code == 200, resolved.text
    out = resolved.json()
    assert out["from_state"] == "RECOVERED"
    assert out["to_state"] == "RESOLVED"
    assert out["previous_revision"] == 3
    assert out["new_revision"] == 4
    assert out["reason"] == reason
    assert out["audited"] is True

    after = client.get(f"/incidents/{iid}/resolve-context", headers=headers)
    assert after.status_code == 200
    assert after.json()["eligible"] is False
    assert after.json()["current_state"] == "RESOLVED"

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT action, outcome, details
            FROM domain.audit_event
            WHERE incident_id = %s AND action = 'incident.manual_resolve'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(iid),),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "incident.manual_resolve"
        assert row[1] == "success"
        details = row[2] if isinstance(row[2], dict) else json.loads(row[2])
        assert details["reason"] == reason
        assert details["path"] == "contextual_manual"
        assert details["health"]["outcome"] == "RECOVERED"

    viewer_id = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (
                id, public_id, state, title, incident_revision
            ) VALUES (%s, %s, 'RECOVERED', 'm7 viewer', 1)
            """,
            (str(viewer_id), f"INC-M7V-{viewer_id.hex[:8]}"),
        )
        conn.commit()

    viewer = {"Authorization": "Bearer local-dev-viewer"}
    forbidden = client.post(
        f"/incidents/{viewer_id}/resolve",
        headers=viewer,
        json={"reason": "nope", "expected_revision": 1},
    )
    assert forbidden.status_code in (401, 403)
