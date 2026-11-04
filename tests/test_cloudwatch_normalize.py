"""F3: CloudWatch adapter → same NormalizedAlert shape as Alertmanager."""

from __future__ import annotations

import json
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "shared", ROOT / "adapters"):
    sys.path.insert(0, str(p))

from incidentpilot_adapters.alerts import (  # noqa: E402
    AlertmanagerAdapter,
    CloudWatchAdapter,
)
from incidentpilot_shared.alerts import NormalizedAlert  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_cloudwatch_sns_fixture_same_shape_as_am() -> None:
    am = AlertmanagerAdapter().normalize(
        {
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
    )
    cw = CloudWatchAdapter().normalize(_load("cloudwatch_alarm_sns.json"))
    assert len(am) == 1 and len(cw) == 1

    am_alert, cw_alert = am[0], cw[0]
    assert {f.name for f in fields(NormalizedAlert)} == {
        f.name for f in fields(type(am_alert))
    }
    assert type(am_alert) is type(cw_alert) is NormalizedAlert

    for name in (
        "fingerprint",
        "source",
        "status",
        "labels",
        "annotations",
        "starts_at",
        "ends_at",
        "raw_payload",
    ):
        assert hasattr(cw_alert, name)

    assert cw_alert.source == "cloudwatch"
    assert am_alert.source == "alertmanager"
    assert cw_alert.status == "firing"
    assert am_alert.status == "firing"
    assert cw_alert.fingerprint.startswith("cw:")
    assert am_alert.fingerprint.startswith("am:")
    assert cw_alert.labels["alertname"] == "SimHighErrorRate"
    assert cw_alert.labels["service"] == "payment"
    assert isinstance(cw_alert.labels, dict)
    assert isinstance(cw_alert.annotations, dict)
    assert isinstance(cw_alert.raw_payload, dict)


def test_cloudwatch_ok_maps_to_resolved() -> None:
    rows = CloudWatchAdapter().normalize(_load("cloudwatch_alarm_ok.json"))
    assert len(rows) == 1
    assert rows[0].status == "resolved"
    assert rows[0].ends_at is not None
    assert rows[0].fingerprint.startswith("cw:")


def test_cloudwatch_fingerprint_stable() -> None:
    adapter = CloudWatchAdapter()
    a = adapter.normalize(_load("cloudwatch_alarm_sns.json"))[0]
    b = adapter.normalize(_load("cloudwatch_alarm_sns.json"))[0]
    assert a.fingerprint == b.fingerprint


def test_subscription_confirmation_skipped() -> None:
    rows = CloudWatchAdapter().normalize(
        {
            "Type": "SubscriptionConfirmation",
            "SubscribeURL": "https://example.invalid/confirm",
            "Token": "abc",
        }
    )
    assert rows == []
