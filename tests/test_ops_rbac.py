"""C2: Ops RBAC role matrix + Admin cannot override Policy BLOCK."""

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
from incidentpilot_api.auth import Principal, Role  # noqa: E402
from incidentpilot_api.rbac import (  # noqa: E402
    Permission,
    assert_approval_allowed_by_policy,
    has_permission,
)

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


def _principal(role: Role) -> Principal:
    return Principal(actor_id=f"user_{role}", role=role, auth_mode="stub")


def test_role_permission_matrix() -> None:
    assert has_permission(_principal(Role.VIEWER), Permission.INCIDENT_READ)
    assert not has_permission(_principal(Role.VIEWER), Permission.APPROVAL_DECIDE)
    assert has_permission(_principal(Role.RESPONDER), Permission.APPROVAL_DECIDE)
    assert has_permission(_principal(Role.ADMIN), Permission.ADMIN_CONFIG)
    assert has_permission(_principal(Role.ADMIN), Permission.APPROVAL_DECIDE)


def test_block_cannot_be_overridden_even_by_logic() -> None:
    with pytest.raises(Exception) as exc:
        assert_approval_allowed_by_policy("BLOCK")
    assert exc.value.status_code == 403  # type: ignore[attr-defined]
    assert "cannot override BLOCK" in str(exc.value.detail)  # type: ignore[attr-defined]


def test_viewer_cannot_approve(client: TestClient) -> None:
    res = client.post(
        f"/approvals/{uuid.uuid4()}/decide",
        headers={"Authorization": "Bearer local-dev-viewer"},
        json={"status": "APPROVED", "action_version": 1},
    )
    assert res.status_code == 403
    assert "approval:decide" in res.json()["detail"]


def _seed_approval(*, policy: str) -> uuid.UUID:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )
    incident_id = uuid.uuid4()
    action_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
                VALUES (%s, %s, 'AWAITING_APPROVAL', 'rbac', 1)
                """,
                (str(incident_id), f"INC-RBAC-{uuid.uuid4().hex[:8]}"),
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
                ) VALUES (%s, 1, %s, 'rbac-test')
                """,
                (str(action_id), policy),
            )
            cur.execute(
                """
                INSERT INTO domain.approval (id, action_id, action_version, status)
                VALUES (%s, %s, 1, 'PENDING')
                """,
                (str(approval_id), str(action_id)),
            )
        conn.commit()
    return approval_id


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_responder_can_approve_when_require_approval(client: TestClient) -> None:
    approval_id = _seed_approval(policy="REQUIRE_APPROVAL")
    res = client.post(
        f"/approvals/{approval_id}/decide",
        headers={"Authorization": "Bearer local-dev"},
        json={"status": "APPROVED", "action_version": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "APPROVED"
    assert res.json()["decided_by"] == "user_local_dev"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_admin_cannot_approve_when_policy_block(client: TestClient) -> None:
    approval_id = _seed_approval(policy="BLOCK")
    res = client.post(
        f"/approvals/{approval_id}/decide",
        headers={"Authorization": "Bearer local-dev-admin"},
        json={"status": "APPROVED", "action_version": 1},
    )
    assert res.status_code == 403, res.text
    assert "cannot override BLOCK" in res.json()["detail"]
