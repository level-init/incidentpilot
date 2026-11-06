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
from incidentpilot_shared.evidence_producers import assert_registered_evidence_producer
from incidentpilot_shared.evidence_projections import persist_evidence_projection

if TYPE_CHECKING:
    from psycopg import Connection


@dataclass(frozen=True, slots=True)
class AppendEvidenceResult:
    evidence_id: UUID
    evidence_key: str
    inserted: bool = True


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


@dataclass(frozen=True, slots=True)
class UpsertAlertResult:
    alert_id: UUID
    fingerprint: str
    inserted: bool


@dataclass(frozen=True, slots=True)
class CreateIncidentResult:
    incident_id: UUID
    public_id: str


@dataclass(frozen=True, slots=True)
class CorrelateAlertResult:
    alert_id: UUID
    incident_id: UUID
    created_incident: bool
    matched_by: str  # existing | fingerprint | service | new


# Alert↔incident correlation window (time/service). Topology is optional (F4).
CORRELATION_WINDOW_MINUTES = 30
_TERMINAL_INCIDENT_STATES = frozenset({"RESOLVED", "CLOSED", "POSTMORTEM"})


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
    """Append factual Evidence (G1) + redacted LLM projection (G2).

    - Only registered producers (never AI sandbox)
    - Server-generated immutable ``evidence_id``
    - Idempotent on ``(incident_id, fingerprint)`` — duplicate scrape returns
      the existing row (``inserted=False``); no UPDATE of factual columns
    - On insert, persist ``domain.evidence_projection`` (READY or BLOCKED);
      canonical ``payload`` is never rewritten
    """
    producer_name = assert_registered_evidence_producer(producer)
    evidence_id = uuid4()
    key = evidence_key or f"EV-{evidence_id.hex[:12]}"
    body = payload or {}
    # G5: never persist fake HIGH RAW without a successful blob upload.
    from incidentpilot_shared.evidence_raw import assert_raw_high_requires_blob

    assert_raw_high_requires_blob(blob_uri=blob_uri, provenance=provenance)
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
            ON CONFLICT (incident_id, fingerprint) DO NOTHING
            RETURNING id, evidence_key
            """,
            (
                str(evidence_id),
                key,
                str(incident_id),
                kind,
                fingerprint,
                summary,
                json.dumps(body),
                json.dumps(provenance or {}),
                blob_uri,
                str(service_id) if service_id else None,
                observed_at,
                producer_name,
            ),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                """
                SELECT id, evidence_key FROM domain.evidence
                WHERE incident_id = %s AND fingerprint = %s
                """,
                (str(incident_id), fingerprint),
            )
            row = cur.fetchone()
            assert row is not None
            if commit:
                conn.commit()
            return AppendEvidenceResult(
                evidence_id=UUID(str(row[0])),
                evidence_key=str(row[1]),
                inserted=False,
            )

    stored_id = UUID(str(row[0]))
    stored_key = str(row[1])
    persist_evidence_projection(
        conn,
        evidence_id=stored_id,
        summary=summary,
        payload=body,
    )
    if commit:
        conn.commit()
    return AppendEvidenceResult(
        evidence_id=stored_id,
        evidence_key=stored_key,
        inserted=True,
    )


def link_evidence_relation_command(
    conn: Connection,
    *,
    from_evidence_id: UUID,
    to_evidence_id: UUID,
    relation_type: str,
    commit: bool = True,
) -> None:
    """Insert an evidence graph edge (idempotent on unique triple)."""
    if relation_type not in {
        "SUPPORTS",
        "CONTRADICTS",
        "DERIVED_FROM",
        "SAME_SIGNAL",
        "TEMPORAL_NEAR",
    }:
        raise ValueError(f"invalid evidence relation_type: {relation_type!r}")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.evidence_relation (
                from_evidence_id, to_evidence_id, relation_type
            ) VALUES (%s, %s, %s)
            ON CONFLICT (from_evidence_id, to_evidence_id, relation_type) DO NOTHING
            """,
            (str(from_evidence_id), str(to_evidence_id), relation_type),
        )
    if commit:
        conn.commit()


def append_derived_evidence_command(
    conn: Connection,
    *,
    incident_id: UUID,
    kind: str,
    fingerprint: str,
    summary: str,
    quality_rule_id: str,
    parent_evidence_ids: list[UUID],
    payload: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
    commit: bool = True,
) -> AppendEvidenceResult:
    """Write DETERMINISTIC_DERIVED Evidence citing RAW parents via DERIVED_FROM.

    Never marks derived rows as RAW. Producer is ``deterministic_processor``.
    """
    if not parent_evidence_ids:
        raise ValueError("derived evidence requires at least one parent")
    if not quality_rule_id.strip():
        raise ValueError("quality_rule_id is required")

    parent_ids = [UUID(str(p)) for p in parent_evidence_ids]
    provenance = {
        "layer": "DETERMINISTIC_DERIVED",
        "quality_rule_id": quality_rule_id.strip(),
        "parent_evidence_ids": [str(p) for p in parent_ids],
    }
    result = append_evidence_command(
        conn,
        incident_id=incident_id,
        kind=kind,
        fingerprint=fingerprint,
        summary=summary,
        producer="deterministic_processor",
        payload=payload,
        provenance=provenance,
        observed_at=observed_at,
        commit=False,
    )
    if result.inserted:
        for parent_id in parent_ids:
            # from=derived, to=parent (derived DERIVED_FROM parent)
            link_evidence_relation_command(
                conn,
                from_evidence_id=result.evidence_id,
                to_evidence_id=parent_id,
                relation_type="DERIVED_FROM",
                commit=False,
            )
    if commit:
        conn.commit()
    return result


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


def upsert_alert_command(
    conn: Connection,
    *,
    fingerprint: str,
    source: str,
    status: str,
    labels: dict[str, Any] | None = None,
    annotations: dict[str, Any] | None = None,
    raw_payload: dict[str, Any] | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    commit: bool = True,
) -> UpsertAlertResult:
    """Insert or update ``domain.alert`` by IncidentPilot fingerprint (F2).

    On conflict, update status / labels / annotations / timestamps /
    raw_payload; keep first ``received_at``, ``id``, and ``incident_id``.
    Call ``correlate_alert_command`` to attach an incident (F4).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.alert (
                fingerprint, source, status, labels, annotations,
                raw_payload, starts_at, ends_at
            ) VALUES (
                %s, %s, %s, %s::jsonb, %s::jsonb,
                %s::jsonb, %s, %s
            )
            ON CONFLICT (fingerprint) DO UPDATE SET
                status = EXCLUDED.status,
                labels = EXCLUDED.labels,
                annotations = EXCLUDED.annotations,
                raw_payload = EXCLUDED.raw_payload,
                starts_at = COALESCE(EXCLUDED.starts_at, domain.alert.starts_at),
                ends_at = EXCLUDED.ends_at
            RETURNING id, (xmax = 0) AS inserted
            """,
            (
                fingerprint,
                source,
                status,
                json.dumps(labels or {}),
                json.dumps(annotations or {}),
                json.dumps(raw_payload or {}),
                starts_at,
                ends_at,
            ),
        )
        row = cur.fetchone()
        assert row is not None
        alert_id = UUID(str(row[0]))
        inserted = bool(row[1])
    if commit:
        conn.commit()
    return UpsertAlertResult(
        alert_id=alert_id,
        fingerprint=fingerprint,
        inserted=inserted,
    )


def _ensure_service_id(
    conn: Connection,
    *,
    service_key: str,
    environment: str = "local",
) -> UUID:
    key = service_key.strip()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.service (key, display_name, environment)
            VALUES (%s, %s, %s)
            ON CONFLICT (key, environment) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    updated_at = now()
            RETURNING id
            """,
            (key, key, environment),
        )
        row = cur.fetchone()
        assert row is not None
        return UUID(str(row[0]))


def create_incident_command(
    conn: Connection,
    *,
    title: str,
    severity: str | None = None,
    summary: str | None = None,
    service_key: str | None = None,
    environment: str = "local",
    actor: str = "system",
    commit: bool = True,
) -> CreateIncidentResult:
    """Create a DETECTED incident (shared by HTTP create + alert correlation)."""
    incident_id = uuid4()
    public_id = f"INC-{incident_id.hex[:8].upper()}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (
                id, public_id, state, title, severity, summary, incident_revision
            ) VALUES (%s, %s, 'DETECTED', %s, %s, %s, 1)
            """,
            (str(incident_id), public_id, title, severity, summary),
        )
        cur.execute(
            """
            INSERT INTO domain.audit_event (
                incident_id, action, actor, resource_type, resource_id, details
            ) VALUES (
                %s, 'incident.create', %s, 'incident', %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                actor,
                str(incident_id),
                json.dumps({"title": title, "source": "command"}),
            ),
        )
    if service_key and service_key.strip():
        service_id = _ensure_service_id(conn, service_key=service_key, environment=environment)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO domain.incident_service (
                    incident_id, service_id, involvement
                ) VALUES (%s, %s, 'affected')
                ON CONFLICT DO NOTHING
                """,
                (str(incident_id), str(service_id)),
            )
    if commit:
        conn.commit()
    return CreateIncidentResult(incident_id=incident_id, public_id=public_id)


def attach_alert_command(
    conn: Connection,
    *,
    alert_id: UUID,
    incident_id: UUID,
    commit: bool = True,
) -> None:
    """Link an alert to an incident (idempotent if already attached)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE domain.alert
            SET incident_id = %s
            WHERE id = %s
              AND (incident_id IS NULL OR incident_id = %s)
            """,
            (str(incident_id), str(alert_id), str(incident_id)),
        )
    if commit:
        conn.commit()


def _find_open_incident_for_fingerprint(conn: Connection, fingerprint: str) -> UUID | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.incident_id
            FROM domain.alert a
            JOIN domain.incident i ON i.id = a.incident_id
            WHERE a.fingerprint = %s
              AND a.incident_id IS NOT NULL
              AND i.state <> ALL(%s)
            LIMIT 1
            """,
            (fingerprint, list(_TERMINAL_INCIDENT_STATES)),
        )
        row = cur.fetchone()
    return UUID(str(row[0])) if row and row[0] else None


def _find_open_incident_for_service(
    conn: Connection,
    *,
    service_key: str,
    window_minutes: int,
) -> UUID | None:
    """Match open incident via recent alert with same labels.service (no topology)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.incident_id
            FROM domain.alert a
            JOIN domain.incident i ON i.id = a.incident_id
            WHERE a.incident_id IS NOT NULL
              AND i.state <> ALL(%s)
              AND a.labels->>'service' = %s
              AND a.received_at >= now() - (%s * interval '1 minute')
            ORDER BY a.received_at DESC
            LIMIT 1
            """,
            (list(_TERMINAL_INCIDENT_STATES), service_key, window_minutes),
        )
        row = cur.fetchone()
    return UUID(str(row[0])) if row and row[0] else None


def correlate_alert_command(
    conn: Connection,
    *,
    alert_id: UUID,
    fingerprint: str,
    labels: dict[str, Any] | None = None,
    annotations: dict[str, Any] | None = None,
    window_minutes: int = CORRELATION_WINDOW_MINUTES,
    actor: str = "system",
    commit: bool = True,
) -> CorrelateAlertResult:
    """Attach alert to an open incident by fingerprint/time/service, or create one.

    Topology/change data is intentionally unused — correlation must work without it.
    """
    labels = labels or {}
    annotations = annotations or {}
    service_key = str(labels.get("service") or "").strip() or None

    with conn.cursor() as cur:
        cur.execute(
            "SELECT incident_id FROM domain.alert WHERE id = %s",
            (str(alert_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"alert {alert_id} not found")
        if row[0] is not None:
            return CorrelateAlertResult(
                alert_id=alert_id,
                incident_id=UUID(str(row[0])),
                created_incident=False,
                matched_by="existing",
            )

    matched = _find_open_incident_for_fingerprint(conn, fingerprint)
    matched_by = "fingerprint"
    if matched is None and service_key:
        matched = _find_open_incident_for_service(
            conn, service_key=service_key, window_minutes=window_minutes
        )
        matched_by = "service"

    if matched is not None:
        attach_alert_command(conn, alert_id=alert_id, incident_id=matched, commit=False)
        if commit:
            conn.commit()
        return CorrelateAlertResult(
            alert_id=alert_id,
            incident_id=matched,
            created_incident=False,
            matched_by=matched_by,
        )

    alertname = str(labels.get("alertname") or "alert").strip()
    summary = str(annotations.get("summary") or "").strip() or None
    if service_key:
        title = summary or f"{alertname} on {service_key}"
    else:
        title = summary or alertname

    created = create_incident_command(
        conn,
        title=title,
        summary=summary,
        service_key=service_key,
        actor=actor,
        commit=False,
    )
    attach_alert_command(conn, alert_id=alert_id, incident_id=created.incident_id, commit=False)
    if commit:
        conn.commit()
    return CorrelateAlertResult(
        alert_id=alert_id,
        incident_id=created.incident_id,
        created_incident=True,
        matched_by="new",
    )
