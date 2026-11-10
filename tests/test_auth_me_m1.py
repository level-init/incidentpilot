"""M1: GET /auth/me exposes session principal for the web shell."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "api", ROOT / "shared"):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_auth_me_requires_bearer(client: TestClient) -> None:
    res = client.get("/auth/me")
    assert res.status_code == 401


def test_auth_me_responder(client: TestClient) -> None:
    res = client.get("/auth/me", headers={"Authorization": "Bearer local-dev"})
    assert res.status_code == 200
    body = res.json()
    assert body["actor_id"] == "user_local_dev"
    assert body["role"] == "responder"
    assert body["auth_mode"] == "stub"
    assert body["email"] == "local-dev@incidentpilot.local"
    assert body["eval_entitled"] is False


def test_auth_me_admin(client: TestClient) -> None:
    res = client.get("/auth/me", headers={"Authorization": "Bearer local-dev-admin"})
    assert res.status_code == 200
    body = res.json()
    assert body["actor_id"] == "user_local_admin"
    assert body["role"] == "admin"
    assert body["eval_entitled"] is False


def test_auth_me_viewer(client: TestClient) -> None:
    res = client.get("/auth/me", headers={"Authorization": "Bearer local-dev-viewer"})
    assert res.status_code == 200
    assert res.json()["role"] == "viewer"
