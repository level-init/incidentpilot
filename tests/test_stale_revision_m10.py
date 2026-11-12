"""M10: stale action_version / revision — reject + client must refresh."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "api", ROOT / "shared", ROOT / "adapters"):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402

psycopg = pytest.importorskip("psycopg")

RESPONDER = {"Authorization": "Bearer local-dev"}


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.approval LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_openapi_decide_requires_action_version(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    body = schema["ApprovalDecideBody"]["properties"]
    assert "action_version" in body
    assert "action_version" in schema["ApprovalDecideBody"].get("required", [])


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_decide_without_action_version_is_422(client: TestClient) -> None:
    # FastAPI may open get_conn_with_permission before body validation.
    res = client.post(
        f"/approvals/{uuid.uuid4()}/decide",
        headers=RESPONDER,
        json={"status": "APPROVED"},
    )
    assert res.status_code == 422


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_stale_approve_rejected_with_stale_action_version(client: TestClient) -> None:
    incident_id = uuid.uuid4()
    action_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'm10 stale', 2)
            """,
            (str(incident_id), f"INC-M10-{uuid.uuid4().hex[:8]}"),
        )
        cur.execute(
            """
            INSERT INTO domain.action (
                id, incident_id, action_type, current_version, proposed_by
            ) VALUES (%s, %s, 'ROLLBACK_DEPLOYMENT', 1, 'system')
            """,
            (str(action_id), str(incident_id)),
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
            INSERT INTO domain.policy_decision (
                action_id, action_version, decision, reason
            ) VALUES (%s, 1, 'REQUIRE_APPROVAL', 'm10')
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

    stale = client.post(
        f"/approvals/{approval_id}/decide",
        headers=RESPONDER,
        json={"status": "APPROVED", "action_version": 99},
    )
    assert stale.status_code == 409, stale.text
    assert "STALE_ACTION_VERSION" in stale.json()["detail"]

    # Still PENDING — client must refresh, not assume success.
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM domain.approval WHERE id = %s", (str(approval_id),))
        assert cur.fetchone()[0] == "PENDING"

    ok = client.post(
        f"/approvals/{approval_id}/decide",
        headers=RESPONDER,
        json={"status": "APPROVED", "action_version": 1},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "APPROVED"
