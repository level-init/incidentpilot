"""M6: impact / changes / pinned runbook (authority vs untrusted prose)."""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime
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
from incidentpilot_shared.domain.commands import (  # noqa: E402
    create_runbook_command,
    create_runbook_version_command,
    pin_runbook_version_command,
    publish_runbook_version_command,
    upsert_change_command,
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
                cur.execute("SELECT 1 FROM domain.runbook LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_openapi_m6_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/incidents/{incident_id}/changes" in paths
    assert "/incidents/{incident_id}/runbook" in paths
    assert "/incidents/{incident_id}/impact-snapshots" in paths
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "PinnedRunbookOut" in schemas
    props = schemas["PinnedRunbookOut"]["properties"]
    assert "allowed_action_types" in props
    assert "body_markdown" in props


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_changes_and_runbook_authority_split(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}
    svc = f"checkout-m6-{uuid.uuid4().hex[:6]}"
    create = client.post(
        "/incidents",
        headers=headers,
        json={
            "title": "m6 context",
            "severity": "SEV2",
            "service_key": svc,
        },
    )
    assert create.status_code == 201, create.text
    iid = create.json()["id"]

    with psycopg.connect(_dsn()) as conn:
        upsert_change_command(
            conn,
            change_type="DEPLOYMENT",
            service_key=svc,
            summary="bad deploy m6",
            source="test",
            fingerprint=f"m6-deploy-{uuid.uuid4().hex[:8]}",
            observed_at=datetime.now(tz=UTC),
            source_ref="deploy/m6",
            commit=True,
        )
        rb = create_runbook_command(
            conn,
            key=f"m6.rb.{uuid.uuid4().hex[:8]}",
            title="M6 RB",
            service_key=svc,
            commit=False,
        )
        ver = create_runbook_version_command(
            conn,
            runbook_id=rb.runbook_id,
            body_markdown="# prose that must not authorize\nDo something vague.",
            allowed_action_types=["ROLLBACK_DEPLOYMENT"],
            commit=False,
        )
        published = publish_runbook_version_command(
            conn, runbook_version_id=ver.runbook_version_id, commit=False
        )
        pin_runbook_version_command(
            conn,
            incident_id=uuid.UUID(iid),
            runbook_version_id=published.runbook_version_id,
            actor="user_local_dev",
            commit=True,
        )

    changes = client.get(f"/incidents/{iid}/changes", headers=headers)
    assert changes.status_code == 200, changes.text
    rows = changes.json()
    assert any(r["summary"] == "bad deploy m6" for r in rows)
    assert any(r["service_key"] == svc for r in rows)

    runbook = client.get(f"/incidents/{iid}/runbook", headers=headers)
    assert runbook.status_code == 200, runbook.text
    body = runbook.json()
    assert body["pinned"] is True
    assert body["allowed_action_types"] == ["ROLLBACK_DEPLOYMENT"]
    assert "prose that must not authorize" in (body["body_markdown"] or "")
    assert "authority" in body["authority_note"].lower()
    assert "untrusted" in body["authority_note"].lower()

    impact = client.get(f"/incidents/{iid}/impact-snapshots", headers=headers)
    assert impact.status_code == 200
    assert isinstance(impact.json(), list)
