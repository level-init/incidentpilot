"""M2: incident list includes service_keys + state/severity/service filters."""

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
                cur.execute("SELECT 1 FROM domain.incident LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_openapi_lists_incident_filters(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    params = {p["name"] for p in paths["/incidents"]["get"].get("parameters", [])}
    assert {"state", "severity", "service"}.issubset(params)
    schema = client.get("/openapi.json").json()["components"]["schemas"]["IncidentOut"]
    assert "service_keys" in schema["properties"]


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_list_shows_service_and_filters(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}
    svc = f"checkout-m2-{uuid.uuid4().hex[:6]}"
    create = client.post(
        "/incidents",
        headers=headers,
        json={
            "title": "m2 list smoke",
            "severity": "SEV2",
            "service_key": svc,
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["severity"] == "SEV2"
    assert body["state"] == "DETECTED"
    assert svc in body["service_keys"]
    assert "local" in body["environments"]

    listed = client.get("/incidents", headers=headers)
    assert listed.status_code == 200
    row = next(r for r in listed.json() if r["id"] == body["id"])
    assert row["severity"] == "SEV2"
    assert row["state"] == "DETECTED"
    assert svc in row["service_keys"]
    assert "local" in row["environments"]
    assert row["opened_at"]

    by_state = client.get("/incidents", headers=headers, params={"state": "DETECTED"})
    assert body["id"] in {r["id"] for r in by_state.json()}

    by_sev = client.get("/incidents", headers=headers, params={"severity": "SEV2"})
    assert body["id"] in {r["id"] for r in by_sev.json()}

    by_svc = client.get("/incidents", headers=headers, params={"service": svc})
    assert {r["id"] for r in by_svc.json()} == {body["id"]}

    miss = client.get(
        "/incidents",
        headers=headers,
        params={"service": f"missing-{uuid.uuid4().hex[:6]}"},
    )
    assert body["id"] not in {r["id"] for r in miss.json()}
