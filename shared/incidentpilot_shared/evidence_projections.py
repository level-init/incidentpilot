"""Evidence LLM projections — redacted views + fail-closed read (G2).

Canonical ``domain.evidence`` stays raw. AI/tool brokers must only consume
``domain.evidence_projection`` via ``read_evidence_projection_for_llm``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from incidentpilot_shared.redaction import (
    EvidenceProjection,
    RedactionError,
    project_evidence_for_llm,
)

if TYPE_CHECKING:
    from psycopg import Connection


@dataclass(frozen=True, slots=True)
class StoredProjectionRef:
    evidence_id: UUID
    status: str  # READY | BLOCKED
    error: str | None = None


def persist_evidence_projection(
    conn: Connection,
    *,
    evidence_id: UUID,
    summary: str,
    payload: dict[str, Any] | None,
) -> StoredProjectionRef:
    """Run C4 redaction and store READY or BLOCKED projection (same TX as insert)."""
    try:
        projection = project_evidence_for_llm(
            summary=summary,
            structured_data=payload or {},
        )
    except RedactionError as exc:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO domain.evidence_projection (
                    evidence_id, status, summary, payload, redacted_fields, error
                ) VALUES (%s, 'BLOCKED', NULL, NULL, '[]'::jsonb, %s)
                ON CONFLICT (evidence_id) DO NOTHING
                """,
                (str(evidence_id), str(exc)),
            )
        return StoredProjectionRef(evidence_id=evidence_id, status="BLOCKED", error=str(exc))

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.evidence_projection (
                evidence_id, status, summary, payload, redacted_fields, error
            ) VALUES (
                %s, 'READY', %s, %s::jsonb, %s::jsonb, NULL
            )
            ON CONFLICT (evidence_id) DO NOTHING
            """,
            (
                str(evidence_id),
                projection.summary,
                json.dumps(projection.structured_data),
                json.dumps(list(projection.redacted_fields)),
            ),
        )
    return StoredProjectionRef(evidence_id=evidence_id, status="READY")


def read_evidence_projection_for_llm(
    conn: Connection,
    *,
    incident_id: UUID,
    evidence_id: UUID,
) -> EvidenceProjection:
    """Fail-closed LLM supply gate.

    Never returns canonical ``domain.evidence.payload``. Missing / BLOCKED
    projections raise ``RedactionError`` so the tool broker must not invoke the model.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.status, p.summary, p.payload, p.redacted_fields, p.error
            FROM domain.evidence_projection p
            JOIN domain.evidence e ON e.id = p.evidence_id
            WHERE p.evidence_id = %s
              AND e.incident_id = %s
            """,
            (str(evidence_id), str(incident_id)),
        )
        row = cur.fetchone()

    if row is None:
        raise RedactionError(
            f"no evidence projection for evidence_id={evidence_id} incident_id={incident_id}"
        )

    status, summary, payload, redacted_fields, error = row
    if status != "READY":
        raise RedactionError(f"evidence projection blocked for {evidence_id}: {error or status}")
    if summary is None or payload is None:
        raise RedactionError(f"evidence projection incomplete for {evidence_id}")

    fields: tuple[str, ...]
    if isinstance(redacted_fields, list):
        fields = tuple(str(x) for x in redacted_fields)
    else:
        fields = tuple(json.loads(redacted_fields)) if redacted_fields else ()

    structured = payload if isinstance(payload, dict) else json.loads(payload)
    return EvidenceProjection(
        summary=str(summary),
        structured_data=structured,
        redacted_fields=fields,
    )
