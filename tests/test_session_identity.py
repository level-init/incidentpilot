"""C1: session-bound actor_id; reject client spoofing."""

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
    ROOT / "scenario_runner",
    ROOT / "evaluator",
):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402
from incidentpilot_api.auth import resolve_bearer_token  # noqa: E402

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


def test_stub_token_binds_actor_id() -> None:
    principal = resolve_bearer_token("local-dev")
    assert principal.actor_id == "user_local_dev"
    assert principal.auth_mode == "stub"


def test_spoofed_actor_id_in_body_rejected(client: TestClient) -> None:
    res = client.post(
        "/incidents",
        headers={"Authorization": "Bearer local-dev"},
        json={"title": "spoof", "actor_id": "evil-user"},
    )
    assert res.status_code == 400
    assert "actor_id" in res.json()["detail"]


def test_spoofed_decided_by_rejected(client: TestClient) -> None:
    res = client.post(
        f"/approvals/{uuid.uuid4()}/decide",
        headers={"Authorization": "Bearer local-dev"},
        json={"status": "APPROVED", "decided_by": "evil"},
    )
    assert res.status_code == 400
    assert "decided_by" in res.json()["detail"]


def test_viewer_token_forbidden_from_create(client: TestClient) -> None:
    res = client.post(
        "/incidents",
        headers={"Authorization": "Bearer local-dev-viewer"},
        json={"title": "nope"},
    )
    assert res.status_code == 403


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_human_observation_uses_session_actor(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}
    created = client.post(
        "/incidents",
        headers=headers,
        json={"title": "obs session"},
    )
    assert created.status_code == 201, created.text
    incident_id = created.json()["id"]

    obs = client.post(
        f"/incidents/{incident_id}/observations",
        headers=headers,
        json={"summary": "saw elevated error rate", "payload": {"zone": "a"}},
    )
    assert obs.status_code == 201, obs.text
    body = obs.json()
    assert body["kind"] == "HUMAN_OBSERVATION"
    assert body["producer"] == "session:user_local_dev"

    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT provenance->>'actor_id' FROM domain.evidence WHERE id = %s",
            (body["id"],),
        )
        assert cur.fetchone()[0] == "user_local_dev"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_approval_decide_uses_session_actor(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}
    created = client.post(
        "/incidents",
        headers=headers,
        json={"title": "approval session"},
    )
    assert created.status_code == 201
    incident_id = created.json()["id"]

    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )
    action_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO domain.action (
                    id, incident_id, action_type, current_version,
                    is_reversible, proposed_by
                ) VALUES (%s, %s, 'ROLLBACK_DEPLOYMENT', 1, false, 'system')
                """,
                (str(action_id), incident_id),
            )
            cur.execute(
                """
                INSERT INTO domain.action_version (
                    action_id, version, action_type, proposed_by
                ) VALUES (%s, 1, 'ROLLBACK_DEPLOYMENT', 'system')
                """,
                (str(action_id),),
            )
            cur.execute(
                """
                INSERT INTO domain.approval (id, action_id, action_version, status)
                VALUES (%s, %s, 1, 'PENDING')
                """,
                (str(approval_id), str(action_id)),
            )
        conn.commit()

    decided = client.post(
        f"/approvals/{approval_id}/decide",
        headers=headers,
        json={"status": "APPROVED"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["decided_by"] == "user_local_dev"
    assert decided.json()["status"] == "APPROVED"
