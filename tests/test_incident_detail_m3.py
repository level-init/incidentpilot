"""M3: incident detail header fields (incl. env) + timeline pane API."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "api", ROOT / "shared"):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402

psycopg = pytest.importorskip("psycopg")


def _db_available() -> bool:
    try:
        url = os.environ.get(
            "DATABASE_URL",
            "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
        )
        with psycopg.connect(url, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.timeline_event LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_openapi_incident_has_environments(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()["components"]["schemas"]["IncidentOut"]
    assert "environments" in schema["properties"]
    paths = client.get("/openapi.json").json()["paths"]
    assert "/incidents/{incident_id}/timeline" in paths


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_detail_header_and_timeline(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}
    svc = f"pay-m3-{uuid.uuid4().hex[:6]}"
    create = client.post(
        "/incidents",
        headers=headers,
        json={
            "title": "m3 detail smoke",
            "severity": "SEV1",
            "service_key": svc,
            "summary": "checkout errors",
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["state"] == "DETECTED"
    assert body["severity"] == "SEV1"
    assert svc in body["service_keys"]
    assert "local" in body["environments"]

    by_uuid = client.get(f"/incidents/{body['id']}", headers=headers)
    assert by_uuid.status_code == 200
    assert by_uuid.json()["public_id"] == body["public_id"]

    by_public = client.get(f"/incidents/{body['public_id']}", headers=headers)
    assert by_public.status_code == 200
    assert by_public.json()["id"] == body["id"]
    assert by_public.json()["environments"] == ["local"]

    timeline = client.get(
        f"/incidents/{body['id']}/timeline",
        headers=headers,
        params={"order": "asc"},
    )
    assert timeline.status_code == 200
    events = timeline.json()
    assert events
    assert events[0]["event_type"] == "INCIDENT_CREATED"
    assert events[0]["incident_id"] == body["id"]
