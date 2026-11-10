"""K6: Slack slash commands against an active incident."""

from __future__ import annotations

import os
import sys
import time
import uuid
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
from incidentpilot_shared.slack_commands import (  # noqa: E402
    dump_command_catalog,
    handle_slash_command,
    parse_slash_text,
    slack_user_may_mutate,
)

psycopg = pytest.importorskip("psycopg")

PATH = "/webhooks/slack/commands"
SECRET = "test-slack-signing-secret-k6"


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.incident LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def slack_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("SLACK_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("SLACK_COMMANDS_OPEN", "1")
    return SECRET


def test_parse_slash_text() -> None:
    assert parse_slash_text("status INC-ABC") == ("status", ["INC-ABC"])
    assert parse_slash_text("")[0] == "help"


def test_command_catalog_includes_designed_set() -> None:
    catalog = dump_command_catalog()
    for name in (
        "status",
        "evidence",
        "hypotheses",
        "timeline",
        "impact",
        "approve",
        "reject",
        "escalate",
        "resolve",
    ):
        assert name in catalog


def test_mutate_authz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLACK_COMMANDS_OPEN", raising=False)
    monkeypatch.setenv("SLACK_COMMAND_RESPONDERS", "U_OK")
    assert slack_user_may_mutate("U_OK") is True
    assert slack_user_may_mutate("U_NO") is False


def test_openapi_includes_slash_commands(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert PATH in paths


def test_invalid_signature_rejected(client: TestClient, slack_secret: str) -> None:
    raw = urlencode({"text": "help", "user_id": "U1"}).encode()
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": "v0=" + ("0" * 64),
    }
    res = client.post(PATH, content=raw, headers=headers)
    assert res.status_code == 401


def _signed(form: dict[str, str], *, secret: str) -> tuple[bytes, dict[str, str]]:
    raw = urlencode(form).encode()
    ts = str(int(time.time()))
    sig = compute_slack_signature(secret=secret, timestamp=ts, raw_body=raw)
    return raw, {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
    }


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_slash_status_evidence_resolve(
    client: TestClient, slack_secret: str
) -> None:
    iid = uuid.uuid4()
    public_id = f"INC-K6-{iid.hex[:8]}"
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (
                id, public_id, state, title, incident_revision
            ) VALUES (%s, %s, 'RECOVERED', 'K6 slash', 2)
            """,
            (str(iid), public_id),
        )
        cur.execute(
            """
            INSERT INTO domain.evidence (
                id, evidence_key, incident_id, kind, fingerprint,
                summary, payload, provenance, producer, observed_at
            ) VALUES (
                %s, %s, %s, 'METRIC', %s,
                'err rate', '{}'::jsonb, '{}'::jsonb, 'test_producer', now()
            )
            """,
            (str(uuid.uuid4()), f"EV-k6-{iid.hex[:6]}", str(iid), f"fp-{iid.hex}"),
        )
        conn.commit()

    raw, headers = _signed(
        {"command": "/ip", "text": f"status {public_id}", "user_id": "U_K6"},
        secret=slack_secret,
    )
    res = client.post(PATH, content=raw, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert public_id in body["text"]
    assert "RECOVERED" in body["text"]

    raw2, headers2 = _signed(
        {"command": "/ip", "text": f"evidence {public_id}", "user_id": "U_K6"},
        secret=slack_secret,
    )
    ev = client.post(PATH, content=raw2, headers=headers2)
    assert ev.status_code == 200
    assert "METRIC" in ev.json()["text"]

    raw3, headers3 = _signed(
        {"command": "/ip", "text": f"resolve {public_id}", "user_id": "U_K6"},
        secret=slack_secret,
    )
    resolved = client.post(PATH, content=raw3, headers=headers3)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["ok"] is True
    assert "RESOLVED" in resolved.json()["text"]

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SELECT state FROM domain.incident WHERE id = %s", (str(iid),))
        assert cur.fetchone()[0] == "RESOLVED"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_slash_mutate_forbidden_without_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SLACK_COMMANDS_OPEN", raising=False)
    monkeypatch.setenv("SLACK_COMMAND_RESPONDERS", "U_ALLOWED")
    iid = uuid.uuid4()
    public_id = f"INC-K6F-{iid.hex[:8]}"
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (
                id, public_id, state, title, incident_revision
            ) VALUES (%s, %s, 'RECOVERED', 'K6 forbid', 1)
            """,
            (str(iid), public_id),
        )
        conn.commit()
        result = handle_slash_command(
            conn,
            text=f"resolve {public_id}",
            slack_user_id="U_DENIED",
            commit=True,
        )
    assert result.ok is False
    assert result.code == "FORBIDDEN"
