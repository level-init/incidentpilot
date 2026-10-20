"""B8: OpenAPI surface + auth stub + incident path."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "api",
    ROOT / "shared",
    ROOT / "worker",
    ROOT / "remediation_worker",
    ROOT / "adapters",
    ROOT / "scenario_runner",
    ROOT / "evaluator",
):
    sys.path.insert(0, str(p))

fastapi = pytest.importorskip("fastapi")
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


def test_health_public(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_openapi_json_validates(client: TestClient) -> None:
    res = client.get("/openapi.json")
    assert res.status_code == 200
    spec = res.json()
    assert spec["info"]["title"] == "IncidentPilot API"
    paths = spec["paths"]
    for required in (
        "/health",
        "/incidents",
        "/alerts",
        "/evidence",
        "/hypotheses",
        "/actions",
        "/approvals",
        "/eval/ground-truth",
    ):
        assert required in paths


def test_published_openapi_file_exists_and_matches_app(client: TestClient) -> None:
    published = ROOT / "openapi" / "openapi.json"
    assert published.is_file(), "run: make openapi-export"
    on_disk = json.loads(published.read_text(encoding="utf-8"))
    live = client.get("/openapi.json").json()
    assert on_disk["info"]["title"] == live["info"]["title"]
    assert set(on_disk["paths"].keys()) == set(live["paths"].keys())


def test_incidents_require_auth(client: TestClient) -> None:
    res = client.get("/incidents")
    assert res.status_code == 401


def test_viewer_forbidden_from_create(client: TestClient) -> None:
    res = client.post(
        "/incidents",
        headers={"Authorization": "Bearer local-dev-viewer"},
        json={"title": "should fail"},
    )
    assert res.status_code == 403


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_incident_create_and_list(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}
    create = client.post(
        "/incidents",
        headers=headers,
        json={"title": "openapi smoke", "severity": "SEV2"},
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["state"] == "DETECTED"
    assert body["incident_revision"] == 1

    listed = client.get("/incidents", headers=headers)
    assert listed.status_code == 200
    ids = {row["id"] for row in listed.json()}
    assert body["id"] in ids
