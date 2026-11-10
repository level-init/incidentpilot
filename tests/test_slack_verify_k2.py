"""K2: Slack signature verify on api; persist interaction before 200."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

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
from incidentpilot_api.slack_signing import compute_slack_signature  # noqa: E402

psycopg = pytest.importorskip("psycopg")

PATH = "/webhooks/slack/interactions"
SECRET = "test-slack-signing-secret"


def _db_available() -> bool:
    try:
        url = os.environ.get(
            "DATABASE_URL",
            "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
        )
        with psycopg.connect(url, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.slack_interaction LIMIT 1")
            return True
    except Exception:
        return False


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def slack_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SECRET)
    return SECRET


def _signed_headers(secret: str, raw: bytes, *, ts: int | None = None) -> dict[str, str]:
    timestamp = str(int(time.time()) if ts is None else ts)
    sig = compute_slack_signature(secret=secret, timestamp=timestamp, raw_body=raw)
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": sig,
    }


def _form_body(payload: dict) -> bytes:
    return urlencode({"payload": json.dumps(payload, separators=(",", ":"))}).encode()


def test_missing_signing_secret_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    raw = _form_body({"type": "block_actions", "trigger_id": "t1"})
    res = client.post(
        PATH,
        content=raw,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res.status_code == 503


def test_invalid_signature_rejected(client: TestClient, slack_secret: str) -> None:
    raw = _form_body({"type": "block_actions", "trigger_id": "forge-1"})
    headers = _signed_headers(slack_secret, raw)
    headers["X-Slack-Signature"] = "v0=" + ("0" * 64)
    res = client.post(PATH, content=raw, headers=headers)
    assert res.status_code == 401
    assert "signature" in res.json()["detail"].lower()


def test_stale_timestamp_rejected(client: TestClient, slack_secret: str) -> None:
    raw = _form_body({"type": "block_actions", "trigger_id": "stale-1"})
    headers = _signed_headers(slack_secret, raw, ts=int(time.time()) - 60 * 10)
    res = client.post(PATH, content=raw, headers=headers)
    assert res.status_code == 401
    assert "timestamp" in res.json()["detail"].lower()


def test_openapi_includes_slack_interactions(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert PATH in paths


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0016 not reachable")
def test_valid_interaction_persisted_before_200(
    client: TestClient, slack_secret: str
) -> None:
    trigger = f"trig-{os.urandom(8).hex()}"
    payload = {
        "type": "block_actions",
        "trigger_id": trigger,
        "user": {"id": "U123", "username": "responder"},
        "actions": [{"action_id": "approve", "value": "approval-xyz"}],
    }
    raw = _form_body(payload)
    headers = _signed_headers(slack_secret, raw)
    res = client.post(PATH, content=raw, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted"
    assert body["idempotent"] is False
    assert body["interaction_type"] == "block_actions"
    interaction_id = body["interaction_id"]
    assert interaction_id

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, slack_trigger_id, payload->>'type'
            FROM domain.slack_interaction WHERE id = %s
            """,
            (interaction_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "RECEIVED"
    assert row[1] == trigger
    assert row[2] == "block_actions"


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0016 not reachable")
def test_duplicate_trigger_is_idempotent(client: TestClient, slack_secret: str) -> None:
    trigger = f"trig-{os.urandom(8).hex()}"
    payload = {"type": "block_actions", "trigger_id": trigger, "actions": []}
    raw = _form_body(payload)
    headers = _signed_headers(slack_secret, raw)
    first = client.post(PATH, content=raw, headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "accepted"

    headers2 = _signed_headers(slack_secret, raw)
    second = client.post(PATH, content=raw, headers=headers2)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["idempotent"] is True
    assert second.json()["interaction_id"] == first.json()["interaction_id"]
