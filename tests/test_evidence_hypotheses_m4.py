"""M4: evidence/hypotheses list expose provenance; citations + HUMAN_OBSERVATION."""

from __future__ import annotations

import os
import sys
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
                cur.execute("SELECT 1 FROM domain.evidence LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_openapi_evidence_hypothesis_provenance(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "provenance" in schemas["EvidenceOut"]["properties"]
    assert "provenance" in schemas["HypothesisOut"]["properties"]
    assert "cited_evidence_ids" in schemas["HypothesisOut"]["properties"]


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_observation_provenance_and_lists(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}
    create = client.post(
        "/incidents",
        headers=headers,
        json={"title": "m4 panes", "severity": "SEV2", "service_key": "checkout"},
    )
    assert create.status_code == 201, create.text
    iid = create.json()["id"]

    obs = client.post(
        f"/incidents/{iid}/observations",
        headers=headers,
        json={"summary": "saw elevated checkout latency"},
    )
    assert obs.status_code == 201, obs.text
    body = obs.json()
    assert body["kind"] == "HUMAN_OBSERVATION"
    assert body["provenance"]["truthfulness"] == "human_note"
    assert body["provenance"]["actor_id"] == "user_local_dev"
    assert body["producer"].startswith("session:")

    listed = client.get("/evidence", headers=headers, params={"incident_id": iid})
    assert listed.status_code == 200
    row = next(r for r in listed.json() if r["id"] == body["id"])
    assert row["provenance"]["source"] == "HUMAN_OBSERVATION"
    assert "producer" in row

    hy = client.get("/hypotheses", headers=headers, params={"incident_id": iid})
    assert hy.status_code == 200
    assert isinstance(hy.json(), list)

    viewer = client.post(
        f"/incidents/{iid}/observations",
        headers={"Authorization": "Bearer local-dev-viewer"},
        json={"summary": "viewer should fail"},
    )
    assert viewer.status_code == 403
