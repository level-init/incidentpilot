"""Alertmanager AlertProvider adapter (wraps shared F2 normalizer)."""

from __future__ import annotations

from typing import Any

from incidentpilot_shared.alerts import NormalizedAlert, normalize_alertmanager_webhook


class AlertmanagerAdapter:
    name = "alertmanager"

    def normalize(self, payload: dict[str, Any]) -> list[NormalizedAlert]:
        return normalize_alertmanager_webhook(payload)
