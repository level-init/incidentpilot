"""CloudWatch / SNS AlertProvider adapter (F3)."""

from __future__ import annotations

from typing import Any

from incidentpilot_shared.alerts import NormalizedAlert, normalize_cloudwatch_payload


class CloudWatchAdapter:
    """Normalize CloudWatch alarm (direct or SNS-wrapped) to ``NormalizedAlert``."""

    name = "cloudwatch"

    def normalize(self, payload: dict[str, Any]) -> list[NormalizedAlert]:
        return normalize_cloudwatch_payload(payload)
