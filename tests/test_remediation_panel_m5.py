"""M5: remediation panel aggregate — scope + UNKNOWN unsafe-to-retry."""

from __future__ import annotations

import json
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


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.execution_attempt LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_openapi_remediation_route(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/incidents/{incident_id}/remediation" in paths
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "RemediationActionOut" in schemas
    props = schemas["RemediationActionOut"]["properties"]
    for key in (
        "parameters",
        "target_ref",
        "risk",
        "policy",
        "approval",
        "attempts",
    ):
        assert key in props


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_remediation_shows_scope_and_unknown_unsafe(client: TestClient) -> None:
    headers = {"Authorization": "Bearer local-dev"}
    create = client.post(
        "/incidents",
        headers=headers,
        json={"title": "m5 remediation", "severity": "SEV1"},
    )
    assert create.status_code == 201, create.text
    iid = create.json()["id"]
    action_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    attempt_id = uuid.uuid4()

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.action (
                id, incident_id, action_type, current_version, status,
                proposed_by, is_reversible
            ) VALUES (%s, %s, 'ROLLBACK_DEPLOYMENT', 1, 'AWAITING_APPROVAL',
                      'system', false)
            """,
            (str(action_id), iid),
        )
        cur.execute(
            """
            INSERT INTO domain.action_version (
                action_id, version, action_type, parameters, target_ref, proposed_by
            ) VALUES (
                %s, 1, 'ROLLBACK_DEPLOYMENT',
                %s::jsonb, %s::jsonb, 'system'
            )
            """,
            (
                str(action_id),
                json.dumps({"deployment": "checkout", "revision": "prev"}),
                json.dumps({"service": "checkout"}),
            ),
        )
        cur.execute(
            """
            INSERT INTO domain.policy_decision (
                action_id, action_version, decision, reason, policy_key, policy_version
            ) VALUES (%s, 1, 'REQUIRE_APPROVAL', 'risk gate', 'default', '1')
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
        cur.execute(
            """
            INSERT INTO domain.execution_attempt (
                id, action_id, action_version, attempt_number, state, adapter_result
            ) VALUES (
                %s, %s, 1, 1, 'UNKNOWN',
                '{"reconciliation_state":"UNKNOWN"}'::jsonb
            )
            """,
            (str(attempt_id), str(action_id)),
        )
        conn.commit()

    res = client.get(f"/incidents/{iid}/remediation", headers=headers)
    assert res.status_code == 200, res.text
    cards = res.json()
    assert len(cards) == 1
    card = cards[0]
    assert card["action_type"] == "ROLLBACK_DEPLOYMENT"
    assert card["current_version"] == 1
    assert card["risk"] == "irreversible"
    assert card["parameters"]["deployment"] == "checkout"
    assert card["target_ref"]["service"] == "checkout"
    assert card["policy"]["decision"] == "REQUIRE_APPROVAL"
    assert card["approval"]["status"] == "PENDING"
    assert card["approval"]["id"] == str(approval_id)
    assert len(card["attempts"]) == 1
    attempt = card["attempts"][0]
    assert attempt["state"] == "UNKNOWN"
    assert attempt["reconciliation_state"] == "UNKNOWN"
    assert attempt["unsafe_to_retry"] is True
    # Must not look like a plain FAILED.
    assert attempt["state"] != "FAILED"

    decide = client.post(
        f"/approvals/{approval_id}/decide",
        headers=headers,
        json={"status": "APPROVED"},
    )
    assert decide.status_code == 200, decide.text
    refreshed = client.get(f"/incidents/{iid}/remediation", headers=headers)
    assert refreshed.json()[0]["approval"]["status"] == "APPROVED"
