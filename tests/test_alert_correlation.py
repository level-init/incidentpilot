"""F4: correlate alerts by fingerprint/time/service → incident."""

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
    ROOT / "adapters",
):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402
from incidentpilot_shared.domain.commands import (  # noqa: E402
    correlate_alert_command,
    upsert_alert_command,
)

psycopg = pytest.importorskip("psycopg")

PATH = "/webhooks/alerts/alertmanager"


def _db_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_db_url(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.alert LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def am_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-am-webhook-token"
    monkeypatch.setenv("ALERTMANAGER_WEBHOOK_TOKEN", token)
    monkeypatch.delenv("ALERTMANAGER_BASIC_USER", raising=False)
    monkeypatch.delenv("ALERTMANAGER_BASIC_PASSWORD", raising=False)
    monkeypatch.delenv("ALERTMANAGER_HEADER_VALUE", raising=False)
    return token


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _am_alert(*, alertname: str, service: str, summary: str = "demo") -> dict:
    return {
        "status": "firing",
        "labels": {
            "alertname": alertname,
            "service": service,
            "uid": uuid.uuid4().hex[:8],
        },
        "annotations": {"summary": summary},
    }


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_related_checkout_alerts_one_incident(client: TestClient, am_token: str) -> None:
    pid = os.getpid()
    first = client.post(
        PATH,
        json={
            "receiver": "incidentpilot",
            "status": "firing",
            "alerts": [
                _am_alert(
                    alertname="CheckoutLatency",
                    service="checkout",
                    summary=f"checkout-a-{pid}",
                )
            ],
        },
        headers={
            "Authorization": f"Bearer {am_token}",
            "Idempotency-Key": f"f4-checkout-a-{pid}",
        },
    )
    second = client.post(
        PATH,
        json={
            "receiver": "incidentpilot",
            "status": "firing",
            "alerts": [
                _am_alert(
                    alertname="CheckoutErrors",
                    service="checkout",
                    summary=f"checkout-b-{pid}",
                )
            ],
        },
        headers={
            "Authorization": f"Bearer {am_token}",
            "Idempotency-Key": f"f4-checkout-b-{pid}",
        },
    )
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["incident_ids"]
    assert first.json()["incident_ids"] == second.json()["incident_ids"]


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_unrelated_services_separate_incidents(client: TestClient, am_token: str) -> None:
    pid = os.getpid()
    checkout = client.post(
        PATH,
        json={
            "receiver": "incidentpilot",
            "status": "firing",
            "alerts": [_am_alert(alertname="X", service="checkout", summary=f"sep-c-{pid}")],
        },
        headers={
            "Authorization": f"Bearer {am_token}",
            "Idempotency-Key": f"f4-sep-checkout-{pid}",
        },
    )
    payment = client.post(
        PATH,
        json={
            "receiver": "incidentpilot",
            "status": "firing",
            "alerts": [_am_alert(alertname="Y", service="payment", summary=f"sep-p-{pid}")],
        },
        headers={
            "Authorization": f"Bearer {am_token}",
            "Idempotency-Key": f"f4-sep-payment-{pid}",
        },
    )
    assert checkout.status_code == 202
    assert payment.status_code == 202
    assert checkout.json()["incident_ids"] != payment.json()["incident_ids"]


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_correlation_without_topology_tables(client: TestClient, am_token: str) -> None:
    """AC: works without change/topology data — command path only uses alert labels."""
    pid = os.getpid()
    res = client.post(
        PATH,
        json={
            "receiver": "incidentpilot",
            "status": "firing",
            "alerts": [_am_alert(alertname="Solo", service="inventory", summary=f"solo-{pid}")],
        },
        headers={
            "Authorization": f"Bearer {am_token}",
            "Idempotency-Key": f"f4-solo-{pid}",
        },
    )
    assert res.status_code == 202, res.text
    incident_id = res.json()["incident_ids"][0]
    with psycopg.connect(_db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT incident_id FROM domain.alert WHERE id = %s",
                (res.json()["alert_ids"][0],),
            )
            assert str(cur.fetchone()[0]) == incident_id
            # No topology required — incident_service may exist from service_key only.
            cur.execute(
                """
                SELECT count(*) FROM domain.incident_service
                WHERE incident_id = %s
                """,
                (incident_id,),
            )
            assert cur.fetchone()[0] >= 1


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_correlate_command_matched_by_service() -> None:
    with psycopg.connect(_db_url()) as conn:
        uid = uuid.uuid4().hex[:8]
        a = upsert_alert_command(
            conn,
            fingerprint=f"am:f4-cmd-a-{uid}",
            source="alertmanager",
            status="firing",
            labels={"alertname": "A", "service": "checkout", "uid": uid},
            annotations={"summary": "a"},
            commit=False,
        )
        c1 = correlate_alert_command(
            conn,
            alert_id=a.alert_id,
            fingerprint=a.fingerprint,
            labels={"alertname": "A", "service": "checkout", "uid": uid},
            annotations={"summary": "a"},
            commit=False,
        )
        b = upsert_alert_command(
            conn,
            fingerprint=f"am:f4-cmd-b-{uid}",
            source="alertmanager",
            status="firing",
            labels={"alertname": "B", "service": "checkout", "uid": uid},
            annotations={"summary": "b"},
            commit=False,
        )
        c2 = correlate_alert_command(
            conn,
            alert_id=b.alert_id,
            fingerprint=b.fingerprint,
            labels={"alertname": "B", "service": "checkout", "uid": uid},
            annotations={"summary": "b"},
            commit=False,
        )
        conn.commit()
        assert c1.created_incident is True
        assert c1.matched_by == "new"
        assert c2.created_incident is False
        assert c2.matched_by == "service"
        assert c1.incident_id == c2.incident_id
