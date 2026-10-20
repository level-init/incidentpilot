"""Shared domain command layer (B7).

API and workers must mutate domain state through these commands — not raw SQL
in adapters. Adapters are outbound integration clients only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from incidentpilot_shared.domain.outbox import UnitOfWork
from incidentpilot_shared.domain.transitions import (
    IncidentState,
    TransitionResult,
    apply_transition,
)

if TYPE_CHECKING:
    from psycopg import Connection


@dataclass(frozen=True, slots=True)
class AppendEvidenceResult:
    evidence_id: UUID
    evidence_key: str


@dataclass(frozen=True, slots=True)
class ApprovalDecisionResult:
    approval_id: UUID
    status: str
    action_id: UUID
    action_version: int


@dataclass(frozen=True, slots=True)
class ReserveAttemptResult:
    attempt_id: UUID
    action_id: UUID
    action_version: int
    attempt_number: int
    state: str


def transition_incident_command(
    conn: Connection,
    *,
    incident_id: UUID,
    expected_revision: int,
    to_state: IncidentState | str,
    actor: str = "system",
    commit: bool = True,
) -> TransitionResult:
    """Transition incident with revision guard + outbox + timeline event."""
    uow = UnitOfWork(conn, requires_outbox=True)
    result = apply_transition(
        conn,
        incident_id=incident_id,
        expected_revision=expected_revision,
        to_state=to_state,
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (
                %s, 'STATE_TRANSITION', %s, %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                f"{result.from_state} → {result.to_state}",
                actor,
                json.dumps(
                    {
                        "from": result.from_state.value,
                        "to": result.to_state.value,
                        "previous_revision": result.previous_revision,
                        "new_revision": result.new_revision,
                    }
                ),
            ),
        )
    uow.enqueue_outbox(
        aggregate_type="incident",
        aggregate_id=str(incident_id),
        event_type="incident.transitioned",
        payload={
            "from": result.from_state.value,
            "to": result.to_state.value,
            "revision": result.new_revision,
            "actor": actor,
        },
    )
    if commit:
        uow.commit()
    return result


def append_evidence_command(
    conn: Connection,
    *,
    incident_id: UUID,
    kind: str,
    fingerprint: str,
    summary: str,
    producer: str,
    observed_at: datetime | None = None,
    payload: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    service_id: UUID | None = None,
    blob_uri: str | None = None,
    evidence_key: str | None = None,
    commit: bool = True,
) -> AppendEvidenceResult:
    """Append factual Evidence (insert-only; DB forbids UPDATE/DELETE)."""
    evidence_id = uuid4()
    key = evidence_key or f"EV-{evidence_id.hex[:12]}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.evidence (
                id, evidence_key, incident_id, kind, fingerprint,
                summary, payload, provenance, blob_uri, service_id,
                observed_at, producer
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s::jsonb, %s::jsonb, %s, %s,
                COALESCE(%s, now()), %s
            )
            """,
            (
                str(evidence_id),
                key,
                str(incident_id),
                kind,
                fingerprint,
                summary,
                json.dumps(payload or {}),
                json.dumps(provenance or {}),
                blob_uri,
                str(service_id) if service_id else None,
                observed_at,
                producer,
            ),
        )
    if commit:
        conn.commit()
    return AppendEvidenceResult(evidence_id=evidence_id, evidence_key=key)


def decide_approval_command(
    conn: Connection,
    *,
    action_id: UUID,
    action_version: int,
    status: str,
    decided_by: str,
    commit: bool = True,
) -> ApprovalDecisionResult:
    """Record human/harness approval decision for a bound action version."""
    if status not in {"APPROVED", "REJECTED"}:
        raise ValueError("status must be APPROVED or REJECTED")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE domain.approval
            SET status = %s,
                decided_by = %s,
                decided_at = now()
            WHERE action_id = %s
              AND action_version = %s
              AND status = 'PENDING'
            RETURNING id
            """,
            (status, decided_by, str(action_id), action_version),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"no PENDING approval for action {action_id} v{action_version}")
        approval_id = UUID(str(row[0]))

    if commit:
        conn.commit()
    return ApprovalDecisionResult(
        approval_id=approval_id,
        status=status,
        action_id=action_id,
        action_version=action_version,
    )


def reserve_execution_attempt_command(
    conn: Connection,
    *,
    action_id: UUID,
    action_version: int,
    attempt_number: int = 1,
    commit: bool = True,
) -> ReserveAttemptResult:
    """Persist execution_attempt in RESERVED before MITIGATING."""
    attempt_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.execution_attempt (
                id, action_id, action_version, attempt_number, state
            ) VALUES (%s, %s, %s, %s, 'RESERVED')
            """,
            (str(attempt_id), str(action_id), action_version, attempt_number),
        )
    if commit:
        conn.commit()
    return ReserveAttemptResult(
        attempt_id=attempt_id,
        action_id=action_id,
        action_version=action_version,
        attempt_number=attempt_number,
        state="RESERVED",
    )
