"""C3: eval entitlement is separate from ops RBAC."""

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
from incidentpilot_api.auth import Principal, Role, resolve_bearer_token  # noqa: E402
from incidentpilot_api.rbac import Permission, has_permission  # noqa: E402

psycopg = pytest.importorskip("psycopg")


def _db_available() -> bool:
    try:
        url = os.environ.get(
            "DATABASE_URL_EVALUATOR",
            "postgresql://ip_evaluator:incidentpilot_evaluator@localhost:5432/incidentpilot",
        )
        with psycopg.connect(url, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM eval.ground_truth LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_ops_roles_lack_eval_entitlement_by_default() -> None:
    for token in ("local-dev", "local-dev-admin", "local-dev-viewer"):
        principal = resolve_bearer_token(token)
        assert principal.eval_entitled is False
        assert has_permission(principal, Permission.EVAL_GROUND_TRUTH_READ) is False


def test_evaluator_stub_has_eval_entitlement() -> None:
    principal = resolve_bearer_token("local-dev-evaluator")
    assert principal.eval_entitled is True
    assert principal.role is Role.VIEWER
    assert has_permission(principal, Permission.EVAL_GROUND_TRUTH_READ) is True


def test_admin_ops_role_alone_does_not_grant_gt() -> None:
    admin = Principal(
        actor_id="admin",
        role=Role.ADMIN,
        auth_mode="stub",
        eval_entitled=False,
    )
    assert has_permission(admin, Permission.ADMIN_CONFIG) is True
    assert has_permission(admin, Permission.EVAL_GROUND_TRUTH_READ) is False


def test_responder_denied_ground_truth_api(client: TestClient) -> None:
    res = client.get(
        "/eval/ground-truth",
        headers={"Authorization": "Bearer local-dev"},
    )
    assert res.status_code == 403
    assert "eval entitlement" in res.json()["detail"]


def test_admin_denied_ground_truth_api(client: TestClient) -> None:
    res = client.get(
        "/eval/ground-truth",
        headers={"Authorization": "Bearer local-dev-admin"},
    )
    assert res.status_code == 403
    assert "eval entitlement" in res.json()["detail"]


@pytest.mark.skipif(not _db_available(), reason="evaluator DB not reachable")
def test_evaluator_can_read_ground_truth(client: TestClient) -> None:
    scenario_key = f"gt-{uuid.uuid4().hex[:10]}"
    url = os.environ.get(
        "DATABASE_URL_EVALUATOR",
        "postgresql://ip_evaluator:incidentpilot_evaluator@localhost:5432/incidentpilot",
    )
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO eval.ground_truth (scenario_key, answer_payload)
                VALUES (%s, '{"root_cause":"bad_deploy"}'::jsonb)
                """,
                (scenario_key,),
            )
        conn.commit()

    res = client.get(
        "/eval/ground-truth",
        headers={"Authorization": "Bearer local-dev-evaluator"},
        params={"scenario_key": scenario_key},
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["scenario_key"] == scenario_key
    assert rows[0]["answer_payload"]["root_cause"] == "bad_deploy"
