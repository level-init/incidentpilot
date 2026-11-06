"""RAW Evidence provenance + blob upload fallback rules (G5).

HIGH quality RAW requires a successful object-store upload (``blob_uri``).
When the store is down, Evidence may still be written with MEDIUM/LOW quality
using content hash + external_ref — never a fake HIGH.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from incidentpilot_shared.domain.commands import AppendEvidenceResult, append_evidence_command

if TYPE_CHECKING:
    from psycopg import Connection

    from incidentpilot_adapters.blob.protocol import BlobStore

RULE_RAW_BLOB = "raw_blob.v1"


class InvalidRawProvenance(ValueError):
    """Raised when provenance claims HIGH RAW without blob_uri."""


@dataclass(frozen=True, slots=True)
class RawWritePlan:
    blob_uri: str | None
    payload: dict[str, Any]
    provenance: dict[str, Any]


def content_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def plan_raw_evidence_write(
    *,
    payload: dict[str, Any],
    source: str,
    external_ref: dict[str, Any],
    blob_store: BlobStore | None,
    object_key: str,
    max_inline_bytes: int = 32_768,
) -> RawWritePlan:
    """Decide blob_uri + provenance for a RAW evidence write.

    - Upload OK → layer=RAW, quality=HIGH, blob_uri set
    - Upload fail / no store → layer=RAW, quality=MEDIUM, blob_uri=None,
      content_hash + external_ref + blob_status=UPLOAD_FAILED
    """
    digest = content_sha256(payload)
    body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    inline = payload
    if len(body) > max_inline_bytes:
        # Keep a bounded inline summary; full bytes intended for the blob.
        inline = {
            "truncated": True,
            "byte_size": len(body),
            "content_hash": digest,
            "preview_keys": sorted(payload.keys())[:20],
        }

    base_prov: dict[str, Any] = {
        "layer": "RAW",
        "quality_rule_id": RULE_RAW_BLOB,
        "content_hash": digest,
        "source": source,
        "external_ref": external_ref,
    }

    if blob_store is None:
        return RawWritePlan(
            blob_uri=None,
            payload=inline if len(body) > max_inline_bytes else payload,
            provenance={
                **base_prov,
                "quality": "MEDIUM",
                "blob_status": "STORE_UNAVAILABLE",
            },
        )

    try:
        put = blob_store.put(object_key, body, content_type="application/json")
    except Exception as exc:  # noqa: BLE001 — any store failure → fallback
        return RawWritePlan(
            blob_uri=None,
            payload=inline if len(body) > max_inline_bytes else payload,
            provenance={
                **base_prov,
                "quality": "MEDIUM",
                "blob_status": "UPLOAD_FAILED",
                "blob_error": str(exc)[:500],
            },
        )

    return RawWritePlan(
        blob_uri=put.uri,
        payload=inline if len(body) > max_inline_bytes else payload,
        provenance={
            **base_prov,
            "quality": "HIGH",
            "blob_status": "UPLOADED",
            "blob_sha256": put.sha256,
            "blob_bytes": put.byte_size,
        },
    )


def assert_raw_high_requires_blob(
    *,
    blob_uri: str | None,
    provenance: dict[str, Any] | None,
) -> None:
    prov = provenance or {}
    if prov.get("quality") == "HIGH" and prov.get("layer") == "RAW" and not blob_uri:
        raise InvalidRawProvenance(
            "RAW quality=HIGH requires blob_uri; object store upload must succeed"
        )


def append_raw_evidence_with_blob(
    conn: Connection,
    *,
    incident_id: UUID,
    kind: str,
    fingerprint: str,
    summary: str,
    producer: str,
    payload: dict[str, Any],
    source: str,
    external_ref: dict[str, Any],
    blob_store: BlobStore | None,
    object_key: str | None = None,
    observed_at: datetime | None = None,
    commit: bool = True,
) -> AppendEvidenceResult:
    """Upload raw payload (best-effort) then append Evidence with honest provenance."""
    key = object_key or f"incidents/{incident_id}/{producer}/{fingerprint}.json"
    plan = plan_raw_evidence_write(
        payload=payload,
        source=source,
        external_ref=external_ref,
        blob_store=blob_store,
        object_key=key,
    )
    assert_raw_high_requires_blob(blob_uri=plan.blob_uri, provenance=plan.provenance)
    return append_evidence_command(
        conn,
        incident_id=incident_id,
        kind=kind,
        fingerprint=fingerprint,
        summary=summary,
        producer=producer,
        payload=plan.payload,
        provenance=plan.provenance,
        blob_uri=plan.blob_uri,
        observed_at=observed_at,
        commit=commit,
    )
