"""Alertmanager → normalized Alert + IncidentPilot fingerprint (F2).

Vendor AM ``fingerprint`` is an *input* only. Domain uniqueness uses
``incidentpilot_fingerprint`` (``am:<sha256>``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedAlert:
    fingerprint: str
    source: str
    status: str
    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: datetime | None
    ends_at: datetime | None
    raw_payload: dict[str, Any]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _str_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        if val is None:
            continue
        out[str(key)] = str(val)
    return out


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw
    text = str(raw).strip()
    if not text or text.startswith("0001-01-01"):
        return None
    # Alertmanager uses RFC3339; fromisoformat accepts offset with colon.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


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
    material = {
        "provider": "alertmanager",
        "alertname": labels.get("alertname", ""),
        "labels": {k: labels[k] for k in sorted(labels)},
        "provider_fingerprint": provider_fingerprint or "",
    }
    digest = hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()
    return f"am:{digest}"


def normalize_alertmanager_alert(raw: dict[str, Any]) -> NormalizedAlert:
    labels = _str_map(raw.get("labels"))
    annotations = _str_map(raw.get("annotations"))
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
        starts_at=_parse_ts(raw.get("startsAt")),
        ends_at=_parse_ts(raw.get("endsAt")),
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
