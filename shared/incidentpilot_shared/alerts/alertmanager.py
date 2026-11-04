"""Alertmanager → normalized Alert + IncidentPilot fingerprint (F2).

Vendor AM ``fingerprint`` is an *input* only. Domain uniqueness uses
``incidentpilot_fingerprint`` (``am:<sha256>``).
"""

from __future__ import annotations

from typing import Any

from incidentpilot_shared.alerts.types import (
    NormalizedAlert,
    fingerprint_for,
    parse_ts,
    str_map,
)


def _map_status(raw: Any) -> str:
    status = str(raw or "firing").strip().lower()
    if status in {"firing", "resolved", "suppressed"}:
        return status
    if status in {"active", "open"}:
        return "firing"
    if status in {"ok", "closed"}:
        return "resolved"
    return "firing"


def incidentpilot_fingerprint(
    *,
    labels: dict[str, str],
    provider_fingerprint: str | None = None,
) -> str:
    """Stable IncidentPilot fingerprint for an Alertmanager alert instance."""
    return fingerprint_for(
        provider="alertmanager",
        prefix="am",
        labels=labels,
        provider_fingerprint=provider_fingerprint,
    )


def normalize_alertmanager_alert(raw: dict[str, Any]) -> NormalizedAlert:
    labels = str_map(raw.get("labels"))
    annotations = str_map(raw.get("annotations"))
    provider_fp = raw.get("fingerprint")
    provider_fp_s = str(provider_fp).strip() if provider_fp else None
    return NormalizedAlert(
        fingerprint=incidentpilot_fingerprint(
            labels=labels,
            provider_fingerprint=provider_fp_s,
        ),
        source="alertmanager",
        status=_map_status(raw.get("status")),
        labels=labels,
        annotations=annotations,
        starts_at=parse_ts(raw.get("startsAt")),
        ends_at=parse_ts(raw.get("endsAt")),
        raw_payload=dict(raw),
    )


def normalize_alertmanager_webhook(payload: dict[str, Any]) -> list[NormalizedAlert]:
    """Normalize an Alertmanager webhook body into domain Alert candidates."""
    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        return []
    out: list[NormalizedAlert] = []
    for item in alerts:
        if isinstance(item, dict):
            out.append(normalize_alertmanager_alert(item))
    return out
