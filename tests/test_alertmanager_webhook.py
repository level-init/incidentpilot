"""F1/F2: Alertmanager webhook auth, replay, normalize + fingerprint persist."""

from __future__ import annotations

import base64
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

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402

psycopg = pytest.importorskip("psycopg")

PATH = "/webhooks/alerts/alertmanager"
AM_PAYLOAD = {
    "receiver": "incidentpilot",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "SimHighErrorRate", "service": "payment"},
            "annotations": {"summary": "demo"},
        }
    ],
}


def _db_available() -> bool:
    try:
        url = os.environ.get(
            "DATABASE_URL",
            "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
        )
        with psycopg.connect(url, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.idempotency_record LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _skip_temporal_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """F1/F2 tests do not require Temporal (covered in F5)."""

    async def _noop(incident_ids: list) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(
        "incidentpilot_api.routes.webhooks_alerts.start_incident_workflows",
        _noop,
    )


@pytest.fixture()
def am_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-am-webhook-token"
    monkeypatch.setenv("ALERTMANAGER_WEBHOOK_TOKEN", token)
    monkeypatch.delenv("ALERTMANAGER_BASIC_USER", raising=False)
    monkeypatch.delenv("ALERTMANAGER_BASIC_PASSWORD", raising=False)
    monkeypatch.delenv("ALERTMANAGER_HEADER_VALUE", raising=False)
    return token


def test_unauthenticated_rejected(client: TestClient, am_token: str) -> None:
    res = client.post(PATH, json=AM_PAYLOAD)
    assert res.status_code == 401
    assert "alertmanager" in res.json()["detail"].lower()


def test_wrong_bearer_rejected(client: TestClient, am_token: str) -> None:
    res = client.post(
        PATH,
        json=AM_PAYLOAD,
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert res.status_code == 401


def test_unconfigured_auth_returns_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALERTMANAGER_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("ALERTMANAGER_BASIC_USER", raising=False)
    monkeypatch.delenv("ALERTMANAGER_BASIC_PASSWORD", raising=False)
    monkeypatch.delenv("ALERTMANAGER_HEADER_VALUE", raising=False)
    res = client.post(
        PATH,
        json=AM_PAYLOAD,
        headers={"Authorization": "Bearer anything"},
    )
    assert res.status_code == 503


def test_basic_auth_accepted_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALERTMANAGER_WEBHOOK_TOKEN", raising=False)
    monkeypatch.setenv("ALERTMANAGER_BASIC_USER", "am")
    monkeypatch.setenv("ALERTMANAGER_BASIC_PASSWORD", "secret")
    monkeypatch.delenv("ALERTMANAGER_HEADER_VALUE", raising=False)
    blob = base64.b64encode(b"am:secret").decode()
    # Without DB, auth passes then connect fails — assert not 401.
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.post(
            PATH,
            json=AM_PAYLOAD,
            headers={"Authorization": f"Basic {blob}"},
        )
    assert res.status_code != 401
    if _db_available():
        assert res.status_code == 202
    else:
        assert res.status_code == 500


def test_custom_header_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALERTMANAGER_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("ALERTMANAGER_BASIC_USER", raising=False)
    monkeypatch.setenv("ALERTMANAGER_HEADER_NAME", "X-Alertmanager-Token")
    monkeypatch.setenv("ALERTMANAGER_HEADER_VALUE", "hdr-secret")
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.post(
            PATH,
            json=AM_PAYLOAD,
            headers={"X-Alertmanager-Token": "hdr-secret"},
        )
    assert res.status_code != 401
    if _db_available():
        assert res.status_code == 202
    else:
        assert res.status_code == 500


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_accepted_with_bearer(client: TestClient, am_token: str) -> None:
    res = client.post(
        PATH,
        json=AM_PAYLOAD,
        headers={
            "Authorization": f"Bearer {am_token}",
            "Idempotency-Key": f"f1-test-{os.getpid()}-1",
        },
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["status"] == "accepted"
    assert body["idempotent"] is False
    assert body["ingress_id"]
    assert len(body["alert_ids"]) == 1
    assert body["fingerprints"][0].startswith("am:")


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_replay_returns_duplicate(client: TestClient, am_token: str) -> None:
    key = f"f1-replay-{os.getpid()}"
    headers = {
        "Authorization": f"Bearer {am_token}",
        "Idempotency-Key": key,
    }
    first = client.post(PATH, json=AM_PAYLOAD, headers=headers)
    second = client.post(PATH, json=AM_PAYLOAD, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["idempotent"] is True


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_same_payload_different_keys_one_alert_row(client: TestClient, am_token: str) -> None:
    """AC: duplicate webhook delivery must not duplicate domain.alert."""
    payload = {
        "receiver": "incidentpilot",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "fingerprint": f"vendor-{os.getpid()}",
                "labels": {
                    "alertname": "F2Dedupe",
                    "service": "payment",
                    "pid": str(os.getpid()),
                },
                "annotations": {"summary": "dedupe"},
            }
        ],
    }
    headers_a = {
        "Authorization": f"Bearer {am_token}",
        "Idempotency-Key": f"f2-a-{os.getpid()}",
    }
    headers_b = {
        "Authorization": f"Bearer {am_token}",
        "Idempotency-Key": f"f2-b-{os.getpid()}",
    }
    first = client.post(PATH, json=payload, headers=headers_a)
    second = client.post(PATH, json=payload, headers=headers_b)
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["fingerprints"] == second.json()["fingerprints"]
    assert first.json()["alert_ids"] == second.json()["alert_ids"]

    fp = first.json()["fingerprints"][0]
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM domain.alert WHERE fingerprint = %s",
                (fp,),
            )
            assert cur.fetchone()[0] == 1


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_resolve_updates_same_fingerprint(client: TestClient, am_token: str) -> None:
    labels = {
        "alertname": "F2Resolve",
        "service": "payment",
        "pid": str(os.getpid()),
    }
    firing = {
        "receiver": "incidentpilot",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": labels,
                "annotations": {"summary": "up"},
            }
        ],
    }
    resolved = {
        "receiver": "incidentpilot",
        "status": "resolved",
        "alerts": [
            {
                "status": "resolved",
                "labels": labels,
                "annotations": {"summary": "down"},
                "endsAt": "2024-06-01T12:00:00Z",
            }
        ],
    }
    first = client.post(
        PATH,
        json=firing,
        headers={
            "Authorization": f"Bearer {am_token}",
            "Idempotency-Key": f"f2-fire-{os.getpid()}",
        },
    )
    second = client.post(
        PATH,
        json=resolved,
        headers={
            "Authorization": f"Bearer {am_token}",
            "Idempotency-Key": f"f2-resolve-{os.getpid()}",
        },
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["fingerprints"] == second.json()["fingerprints"]
    fp = first.json()["fingerprints"][0]
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM domain.alert WHERE fingerprint = %s",
                (fp,),
            )
            assert cur.fetchone()[0] == "resolved"


def test_openapi_includes_webhook_path(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert PATH in paths
