"""Shared normalized Change shape (G8)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

ALLOWED_CHANGE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "DEPLOYMENT",
        "COMMIT",
        "PULL_REQUEST",
        "FEATURE_FLAG",
        "CONFIG",
        "SCALE",
        "ROLLBACK",
        "OTHER",
    }
)


@dataclass(frozen=True, slots=True)
class NormalizedChange:
    """Vendor-agnostic change candidate — adapters never write ``domain.*``."""

    change_type: str
    service_key: str
    observed_at: datetime
    source_ref: str
    source: str
    fingerprint: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.change_type not in ALLOWED_CHANGE_TYPES:
            raise ValueError(f"unsupported change_type: {self.change_type!r}")
        if not self.service_key.strip():
            raise ValueError("service_key is required")
        if not self.source_ref.strip():
            raise ValueError("source_ref is required")
        if not self.source.strip():
            raise ValueError("source is required")
        if not self.fingerprint.strip():
            raise ValueError("fingerprint is required")
        if not self.summary.strip():
            raise ValueError("summary is required")


def change_fingerprint(
    *,
    source: str,
    change_type: str,
    service_key: str,
    source_ref: str,
) -> str:
    material = {
        "source": source,
        "change_type": change_type,
        "service_key": service_key,
        "source_ref": source_ref,
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"chg:{source}:{digest}"
