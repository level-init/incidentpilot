"""K5: HUMAN_OBSERVATION API — session actor only; Responder+; correct Evidence kind."""

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
    ROOT / "worker",
    ROOT / "remediation_worker",
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
                cur.execute("SELECT 1 FROM domain.evidence LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_openapi_includes_observations(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/incidents/{incident_id}/observations" in paths


def test_viewer_cannot_write_observation(client: TestClient) -> None:
    res = client.post(
        f"/incidents/{uuid.uuid4()}/observations",
        headers={"Authorization": "Bearer local-dev-viewer"},
        json={"summary": "nope"},
    )
    assert res.status_code == 403


def test_spoofed_actor_id_on_observation_rejected(client: TestClient) -> None:
    res = client.post(
        f"/incidents/{uuid.uuid4()}/observations",
        headers={"Authorization": "Bearer local-dev"},
        json={"summary": "saw spike", "actor_id": "evil"},
    )
    assert res.status_code == 400
    assert "actor_id" in res.json()["detail"]


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_human_observation_session_actor_and_kind(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}
    created = client.post(
        "/incidents",
        headers=headers,
        json={"title": "k5 observation"},
    )
    assert created.status_code == 201, created.text
    incident_id = created.json()["id"]

    missing = client.post(
        f"/incidents/{uuid.uuid4()}/observations",
        headers=headers,
        json={"summary": "ghost incident"},
    )
    assert missing.status_code == 404

    obs = client.post(
        f"/incidents/{incident_id}/observations",
        headers=headers,
        json={"summary": "checkout latency looks bad", "payload": {"hint": "p99"}},
    )
    assert obs.status_code == 201, obs.text
    body = obs.json()
    assert body["kind"] == "HUMAN_OBSERVATION"
    assert body["producer"] == "session:user_local_dev"
    assert body["incident_id"] == incident_id

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT kind, producer,
                   provenance->>'actor_id',
                   provenance->>'source',
                   provenance->>'truthfulness',
                   provenance->>'absolute_truth'
            FROM domain.evidence WHERE id = %s
            """,
            (body["id"],),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "HUMAN_OBSERVATION"
    assert row[1] == "session:user_local_dev"
    assert row[2] == "user_local_dev"
    assert row[3] == "HUMAN_OBSERVATION"
    assert row[4] == "human_note"
    assert row[5] in ("false", False) or str(row[5]).lower() == "false"
