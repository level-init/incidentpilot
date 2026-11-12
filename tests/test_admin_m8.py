"""M8: Admin policies / runbooks / integrations (scope not secrets)."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "api",
    ROOT / "shared",
    ROOT / "adapters",
):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402

psycopg = pytest.importorskip("psycopg")

ADMIN = {"Authorization": "Bearer local-dev-admin"}
RESPONDER = {"Authorization": "Bearer local-dev"}
VIEWER = {"Authorization": "Bearer local-dev-viewer"}


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.policy_definition LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_openapi_m8_admin_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/admin/policies" in paths
    assert "/admin/runbooks" in paths
    assert "/admin/runbooks/{runbook_id}/versions" in paths
    assert "/admin/runbooks/versions/{runbook_version_id}/publish" in paths
    assert "/admin/integrations" in paths
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "PolicyKeyOut" in schemas
    assert "IntegrationStatusOut" in schemas
    assert "AdminRunbookOut" in schemas


def test_admin_routes_rbac(client: TestClient) -> None:
    for headers in (RESPONDER, VIEWER):
        assert client.get("/admin/policies", headers=headers).status_code == 403
        assert client.get("/admin/runbooks", headers=headers).status_code == 403
        assert client.get("/admin/integrations", headers=headers).status_code == 403


def test_integrations_never_expose_secrets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = f"super-secret-{uuid.uuid4().hex}"
    monkeypatch.setenv("SLACK_SIGNING_SECRET", secret)
    monkeypatch.setenv("SLACK_BOT_TOKEN", f"xoxb-{secret}")
    monkeypatch.setenv("ALERTMANAGER_WEBHOOK_TOKEN", f"am-{secret}")
    monkeypatch.setenv("ALERTMANAGER_BASIC_PASSWORD", secret)
    monkeypatch.setenv("ALERTMANAGER_HEADER_VALUE", secret)
    monkeypatch.setenv("SLACK_NOTIFIER", "http")

    res = client.get("/admin/integrations", headers=ADMIN)
    assert res.status_code == 200, res.text
    payload = res.json()
    blob = json.dumps(payload)
    assert secret not in blob
    assert f"xoxb-{secret}" not in blob
    assert f"am-{secret}" not in blob

    by_key = {row["key"]: row for row in payload}
    assert by_key["slack_inbound"]["configured"] is True
    assert by_key["slack_inbound"]["secrets_exposed"] is False
    assert by_key["slack_inbound"]["scope"]["signing_secret_configured"] is True
    assert by_key["slack_outbound"]["scope"]["bot_token_configured"] is True
    assert by_key["alertmanager_webhook"]["configured"] is True
    assert "bearer" in by_key["alertmanager_webhook"]["scope"]["auth_mechanisms_configured"]
    assert all(row["secrets_exposed"] is False for row in payload)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_admin_policies_and_runbook_publish(client: TestClient) -> None:
    keys = client.get("/admin/policies", headers=ADMIN)
    assert keys.status_code == 200, keys.text
    assert isinstance(keys.json(), list)
    assert any(k["policy_key"] == "default" for k in keys.json())

    history = client.get("/policies/default/versions", headers=ADMIN)
    assert history.status_code == 200, history.text
    assert len(history.json()) >= 1

    rb_key = f"m8.rb.{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/admin/runbooks",
        headers=ADMIN,
        json={
            "key": rb_key,
            "title": "M8 runbook",
            "service_key": f"svc-m8-{uuid.uuid4().hex[:6]}",
        },
    )
    assert created.status_code == 201, created.text
    runbook_id = created.json()["runbook_id"]

    draft = client.post(
        f"/admin/runbooks/{runbook_id}/versions",
        headers=ADMIN,
        json={
            "body_markdown": "# do not treat as authority",
            "allowed_action_types": ["ROLLBACK_DEPLOYMENT"],
        },
    )
    assert draft.status_code == 201, draft.text
    assert draft.json()["status"] == "draft"
    version_id = draft.json()["runbook_version_id"]

    published = client.post(
        f"/admin/runbooks/versions/{version_id}/publish",
        headers=ADMIN,
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    listed = client.get("/admin/runbooks", headers=ADMIN)
    assert listed.status_code == 200, listed.text
    match = next(r for r in listed.json() if r["runbook_id"] == runbook_id)
    assert match["active_version"] == published.json()["version"]
    assert match["active_allowed_action_types"] == ["ROLLBACK_DEPLOYMENT"]
