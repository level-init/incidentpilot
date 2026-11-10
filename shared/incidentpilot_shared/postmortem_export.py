"""Postmortem export package builder + S3 archive (L6).

Export is a demo/archive artifact: timeline, Evidence refs, and postmortem body.
Canonical truth remains in Postgres; S3 holds a snapshot package.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from psycopg import Connection

    from incidentpilot_adapters.blob.protocol import BlobStore

EXPORT_SCHEMA = "postmortem_export.v1"


@dataclass(frozen=True, slots=True)
class PostmortemExportUpload:
    export_uri: str | None
    blob_status: str
    blob_error: str | None = None
    sha256: str | None = None
    byte_size: int | None = None


def build_postmortem_export_package(
    conn: Connection,
    *,
    incident_id: UUID,
) -> dict[str, Any]:
    """Assemble export JSON from SoR (requires FINAL postmortem)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT public_id, title, state, severity, summary,
                   opened_at, resolved_at, closed_at, incident_revision
            FROM domain.incident
            WHERE id = %s
            """,
            (str(incident_id),),
        )
        inc = cur.fetchone()
        if inc is None:
            raise LookupError(f"incident {incident_id} not found")

        cur.execute(
            """
            SELECT id, status, title, body_markdown, corrective_actions,
                   cited_evidence_ids, author, provenance, finalized_at, created_at
            FROM domain.postmortem
            WHERE incident_id = %s
            """,
            (str(incident_id),),
        )
        pm = cur.fetchone()
        if pm is None:
            raise LookupError(f"postmortem not found for incident {incident_id}")
        if str(pm[1]) != "FINAL":
            raise ValueError(
                f"postmortem export requires FINAL status (got {pm[1]})"
            )

        cur.execute(
            """
            SELECT id, event_type, summary, actor, occurred_at, payload
            FROM domain.timeline_event
            WHERE incident_id = %s
            ORDER BY occurred_at ASC, created_at ASC
            """,
            (str(incident_id),),
        )
        timeline_rows = cur.fetchall()

        cur.execute(
            """
            SELECT id, evidence_key, kind, summary, fingerprint, producer, observed_at
            FROM domain.evidence
            WHERE incident_id = %s
            ORDER BY observed_at ASC, ingested_at ASC
            """,
            (str(incident_id),),
        )
        evidence_rows = cur.fetchall()

    cited_raw = pm[5] or []
    cited_evidence_ids = [str(x) for x in cited_raw]
    corrective = pm[4]
    if isinstance(corrective, str):
        corrective = json.loads(corrective)
    provenance = pm[7]
    if isinstance(provenance, str):
        provenance = json.loads(provenance)

    return {
        "schema": EXPORT_SCHEMA,
        "generated_at": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        "incident": {
            "id": str(incident_id),
            "public_id": str(inc[0]),
            "title": str(inc[1]),
            "state": str(inc[2]),
            "severity": None if inc[3] is None else str(inc[3]),
            "summary": None if inc[4] is None else str(inc[4]),
            "opened_at": _ts(inc[5]),
            "resolved_at": _ts(inc[6]),
            "closed_at": _ts(inc[7]),
            "incident_revision": int(inc[8]),
        },
        "postmortem": {
            "id": str(pm[0]),
            "status": str(pm[1]),
            "title": str(pm[2]),
            "body_markdown": str(pm[3]),
            "corrective_actions": corrective if isinstance(corrective, list) else [],
            "cited_evidence_ids": cited_evidence_ids,
            "author": None if pm[6] is None else str(pm[6]),
            "provenance": provenance if isinstance(provenance, dict) else {},
            "finalized_at": _ts(pm[8]),
            "created_at": _ts(pm[9]),
        },
        "timeline": [
            {
                "id": str(row[0]),
                "event_type": str(row[1]),
                "summary": str(row[2]),
                "actor": str(row[3]),
                "occurred_at": _ts(row[4]),
                "payload": row[5] if isinstance(row[5], dict) else {},
            }
            for row in timeline_rows
        ],
        "evidence_refs": [
            {
                "id": str(row[0]),
                "evidence_key": str(row[1]),
                "kind": str(row[2]),
                "summary": str(row[3]),
                "fingerprint": str(row[4]),
                "producer": str(row[5]),
                "observed_at": _ts(row[6]),
            }
            for row in evidence_rows
        ],
    }


def upload_postmortem_export(
    blob_store: BlobStore | None,
    *,
    incident_id: UUID,
    public_id: str,
    package: dict[str, Any],
) -> PostmortemExportUpload:
    """Best-effort S3 put of the export package."""
    if blob_store is None:
        return PostmortemExportUpload(
            export_uri=None,
            blob_status="STORE_UNAVAILABLE",
        )
    body = json.dumps(package, sort_keys=True, default=str).encode("utf-8")
    key = f"postmortems/{public_id}/{incident_id}.json"
    try:
        put = blob_store.put(key, body, content_type="application/json")
    except Exception as exc:  # noqa: BLE001
        return PostmortemExportUpload(
            export_uri=None,
            blob_status="UPLOAD_FAILED",
            blob_error=str(exc)[:500],
        )
    return PostmortemExportUpload(
        export_uri=put.uri,
        blob_status="UPLOADED",
        sha256=put.sha256,
        byte_size=put.byte_size,
    )


def _ts(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
