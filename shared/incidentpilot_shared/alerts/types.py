"""Shared normalized Alert shape (F2+)."""

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


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def str_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        if val is None:
            continue
        out[str(key)] = str(val)
    return out


def parse_ts(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw
    text = str(raw).strip()
    if not text or text.startswith("0001-01-01"):
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def fingerprint_for(
    *,
    provider: str,
    prefix: str,
    labels: dict[str, str],
    provider_fingerprint: str | None = None,
    alertname_key: str = "alertname",
) -> str:
    material = {
        "provider": provider,
        "alertname": labels.get(alertname_key, ""),
        "labels": {k: labels[k] for k in sorted(labels)},
        "provider_fingerprint": provider_fingerprint or "",
    }
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"
