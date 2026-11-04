"""F2: Alertmanager normalize + IncidentPilot fingerprint (unit)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))

from incidentpilot_shared.alerts.alertmanager import (  # noqa: E402
    incidentpilot_fingerprint,
    normalize_alertmanager_webhook,
)


def test_fingerprint_stable_across_label_key_order() -> None:
    a = incidentpilot_fingerprint(
        labels={"service": "payment", "alertname": "SimHighErrorRate"},
        provider_fingerprint="abc",
    )
    b = incidentpilot_fingerprint(
        labels={"alertname": "SimHighErrorRate", "service": "payment"},
        provider_fingerprint="abc",
    )
    assert a == b
    assert a.startswith("am:")


def test_fingerprint_changes_with_labels() -> None:
    a = incidentpilot_fingerprint(labels={"alertname": "A", "service": "payment"})
    b = incidentpilot_fingerprint(labels={"alertname": "A", "service": "checkout"})
    assert a != b


def test_normalize_webhook_maps_alerts() -> None:
    payload = {
        "receiver": "incidentpilot",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "fingerprint": "vendor-1",
                "startsAt": "2024-01-01T00:00:00Z",
                "labels": {"alertname": "SimHighErrorRate", "service": "payment"},
                "annotations": {"summary": "demo"},
            },
            {
                "status": "resolved",
                "endsAt": "2024-01-01T01:00:00Z",
                "labels": {"alertname": "Other", "service": "payment"},
                "annotations": {},
            },
        ],
    }
    rows = normalize_alertmanager_webhook(payload)
    assert len(rows) == 2
    assert rows[0].source == "alertmanager"
    assert rows[0].status == "firing"
    assert rows[0].fingerprint.startswith("am:")
    assert rows[0].raw_payload["fingerprint"] == "vendor-1"
    assert rows[0].starts_at is not None
    assert rows[1].status == "resolved"
    assert rows[1].ends_at is not None


def test_normalize_empty_alerts() -> None:
    assert normalize_alertmanager_webhook({"alerts": []}) == []
    assert normalize_alertmanager_webhook({}) == []
