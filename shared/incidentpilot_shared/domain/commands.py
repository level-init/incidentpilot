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
class UpsertChangeResult:
    change_id: UUID
    change_key: str
    fingerprint: str
    inserted: bool


@dataclass(frozen=True, slots=True)
class RecordAiInvocationResult:
    invocation_id: UUID
    incident_id: UUID | None
    status: str


@dataclass(frozen=True, slots=True)
class ProposeHypothesisResult:
    hypothesis_id: UUID
    incident_id: UUID
    status: str
    proposed_by: str
    heuristic_score: float | None
    cited_evidence_ids: tuple[UUID, ...]
    rank: int | None


@dataclass(frozen=True, slots=True)
class RankHypothesesResult:
    incident_id: UUID
    ranked: tuple[ProposeHypothesisResult, ...]


@dataclass(frozen=True, slots=True)
class DiagnoseIncidentResult:
    incident_id: UUID
    hypothesis_id: UUID
    leading_at: datetime
    from_state: str
    to_state: str
    previous_revision: int
    new_revision: int


@dataclass(frozen=True, slots=True)
class CreateRunbookResult:
    runbook_id: UUID
    key: str


@dataclass(frozen=True, slots=True)
class CreateRunbookVersionResult:
    runbook_version_id: UUID
    runbook_id: UUID
    version: int
    status: str
    allowed_action_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PinRunbookResult:
    incident_id: UUID
    runbook_version_id: UUID
    evidence_id: UUID
    evidence_key: str
    allowed_action_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecordImpactSnapshotResult:
    snapshot_id: UUID
    incident_id: UUID
    severity: str | None
    estimated_affected_users: int | None
    cited_evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class RecordSloBurnResult:
    slo_burn_id: UUID
    incident_id: UUID
    slo_key: str
    window_label: str
    burn_rate: float | None
    error_budget_remaining: float | None
    cited_evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class UpdateIncidentSeverityResult:
    incident_id: UUID
    previous_severity: str | None
    severity: str
    changed: bool
    explanation: str
    quality_rule_id: str
    inputs: dict[str, Any]


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

# H5: DIAGNOSED is a SYSTEM gate — not free-form TransitionIncident.
_DIAGNOSE_ACTORS = frozenset({"system", "incident-workflow"})
# H8: incident.severity is SYSTEM-rules only (AI explains, never sets).
_SEVERITY_ACTORS = frozenset({"system", "incident-workflow"})


class DiagnosedGateError(PermissionError):
    """Raised when DIAGNOSED is requested outside ``diagnose_incident_command``."""


class DiagnoseActorDenied(PermissionError):
    """Raised when a non-SYSTEM actor attempts the LEADING + DIAGNOSED gate."""


class SeverityActorDenied(PermissionError):
    """Raised when a non-SYSTEM actor attempts to set incident severity."""


def transition_incident_command(
    conn: Connection,
    *,
    incident_id: UUID,
    expected_revision: int,
    to_state: IncidentState | str,
    actor: str = "system",
    commit: bool = True,
    via_diagnose_gate: bool = False,
) -> TransitionResult:
    """Transition incident with revision guard + outbox + timeline event.

    ``INVESTIGATING → DIAGNOSED`` is blocked unless ``via_diagnose_gate=True``
    (H5 — only ``diagnose_incident_command`` may set that flag).
    """
    target = IncidentState(to_state) if not isinstance(to_state, IncidentState) else to_state
    if target is IncidentState.DIAGNOSED and not via_diagnose_gate:
        raise DiagnosedGateError(
            "DIAGNOSED is only allowed via diagnose_incident_command (SYSTEM gate)"
        )
    uow = UnitOfWork(conn, requires_outbox=True)
    result = apply_transition(
        conn,
        incident_id=incident_id,
        expected_revision=expected_revision,
        to_state=target,
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


def upsert_change_command(
    conn: Connection,
    *,
    change_type: str,
    service_key: str,
    observed_at: datetime,
    source_ref: str,
    source: str,
    fingerprint: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    environment: str = "local",
    commit: bool = True,
) -> UpsertChangeResult:
    """Insert ``domain.change`` idempotently by ``(source, fingerprint)`` (G8).

    AC mapping: type→``change_type``, service→``service_id``, time→``observed_at``,
    source_ref→``external_ref``. On conflict do nothing — no factual UPDATE.
    """
    from incidentpilot_shared.changes.types import ALLOWED_CHANGE_TYPES

    if change_type not in ALLOWED_CHANGE_TYPES:
        raise ValueError(f"unsupported change_type: {change_type!r}")
    service_id = _ensure_service_id(conn, service_key=service_key, environment=environment)
    change_id = uuid4()
    change_key = f"CHG-{change_id.hex[:12]}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.change (
                id, change_key, change_type, service_id, summary,
                payload, provenance, source, external_ref, fingerprint, observed_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s, %s, %s, %s
            )
            ON CONFLICT (source, fingerprint) DO NOTHING
            RETURNING id, change_key
            """,
            (
                str(change_id),
                change_key,
                change_type,
                str(service_id),
                summary,
                json.dumps(payload or {}),
                json.dumps(provenance or {}),
                source,
                source_ref,
                fingerprint,
                observed_at,
            ),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                """
                SELECT id, change_key FROM domain.change
                WHERE source = %s AND fingerprint = %s
                """,
                (source, fingerprint),
            )
            row = cur.fetchone()
            assert row is not None
            if commit:
                conn.commit()
            return UpsertChangeResult(
                change_id=UUID(str(row[0])),
                change_key=str(row[1]),
                fingerprint=fingerprint,
                inserted=False,
            )
    if commit:
        conn.commit()
    return UpsertChangeResult(
        change_id=UUID(str(row[0])),
        change_key=str(row[1]),
        fingerprint=fingerprint,
        inserted=True,
    )


_AI_INVOCATION_STATUSES = frozenset({"succeeded", "failed", "timeout", "cancelled"})


def record_ai_invocation_command(
    conn: Connection,
    *,
    purpose: str,
    provider: str,
    model: str,
    status: str = "succeeded",
    incident_id: UUID | str | None = None,
    prompt_hash: str | None = None,
    response_hash: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
    error_summary: str | None = None,
    prompt_version: str | None = None,
    input_evidence_ids: list[str] | tuple[str, ...] | None = None,
    request_metadata: dict[str, Any] | None = None,
    response_metadata: dict[str, Any] | None = None,
    artifact_uri: str | None = None,
    commit: bool = True,
) -> RecordAiInvocationResult:
    """Insert minimum ``domain.ai_invocation`` provenance (H2).

    Required AC fields: model, prompt_version + input evidence ids (in
    ``request_metadata``), status, timestamps (``created_at`` default), incident link.
    Full S3 prompt packages are L3 (``artifact_uri`` left null for now).
    """
    if status not in _AI_INVOCATION_STATUSES:
        raise ValueError(f"unsupported ai_invocation status: {status!r}")
    meta = dict(request_metadata or {})
    if prompt_version is not None:
        meta.setdefault("prompt_version", prompt_version)
    if input_evidence_ids is not None:
        meta.setdefault("input_evidence_ids", list(input_evidence_ids))
    invocation_id = uuid4()
    iid = str(incident_id) if incident_id is not None else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.ai_invocation (
                id, incident_id, purpose, provider, model,
                prompt_hash, response_hash, input_tokens, output_tokens, latency_ms,
                status, error_summary, artifact_uri,
                request_metadata, response_metadata
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s::jsonb, %s::jsonb
            )
            RETURNING id
            """,
            (
                str(invocation_id),
                iid,
                purpose,
                provider,
                model,
                prompt_hash,
                response_hash,
                input_tokens,
                output_tokens,
                latency_ms,
                status,
                error_summary,
                artifact_uri,
                json.dumps(meta),
                json.dumps(response_metadata or {}),
            ),
        )
        row = cur.fetchone()
        assert row is not None
    if commit:
        conn.commit()
    return RecordAiInvocationResult(
        invocation_id=UUID(str(row[0])),
        incident_id=UUID(iid) if iid else None,
        status=status,
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


class MissingEvidenceCitationError(ValueError):
    """Raised when a hypothesis cites an unknown or cross-incident Evidence id."""


def resolve_incident_evidence_refs(
    conn: Connection,
    *,
    incident_id: UUID,
    refs: list[str] | tuple[str, ...],
) -> list[UUID]:
    """Resolve ``EV-…`` keys (or uuid strings) to evidence UUIDs on this incident.

    Missing / wrong-incident citations raise ``MissingEvidenceCitationError``.
    Historical assist ids (``HIST-…``, H9) are never Evidence and are rejected.
    """
    from incidentpilot_shared.history import is_historical_suggestion_ref

    if not refs:
        raise MissingEvidenceCitationError("hypothesis requires at least one evidence citation")
    resolved: list[UUID] = []
    seen: set[str] = set()
    with conn.cursor() as cur:
        for raw in refs:
            ref = str(raw).strip()
            if not ref:
                raise MissingEvidenceCitationError("empty evidence citation")
            if is_historical_suggestion_ref(ref):
                raise MissingEvidenceCitationError(
                    f"historical suggestion {ref!r} is not Evidence — "
                    "collect current-incident EV-… citations"
                )
            if ref in seen:
                continue
            seen.add(ref)
            cur.execute(
                """
                SELECT id FROM domain.evidence
                WHERE incident_id = %s
                  AND (evidence_key = %s OR id::text = %s)
                LIMIT 1
                """,
                (str(incident_id), ref, ref),
            )
            row = cur.fetchone()
            if row is None:
                raise MissingEvidenceCitationError(
                    f"missing/unknown evidence citation {ref!r} for incident {incident_id}"
                )
            resolved.append(UUID(str(row[0])))
    return resolved


def propose_hypothesis_command(
    conn: Connection,
    *,
    incident_id: UUID,
    statement: str,
    cited_evidence_ids: list[str] | tuple[str, ...],
    rationale: str | None = None,
    hypothesis_class: str | None = None,
    heuristic_score: float | None = None,
    proposed_by: str = "AI",
    ai_invocation_id: UUID | str | None = None,
    rank: int | None = None,
    commit: bool = True,
) -> ProposeHypothesisResult:
    """SYSTEM write of a PROPOSED hypothesis (H4).

    AI may propose via tools/LLM; only this command inserts ``domain.hypothesis``.
    ``heuristic_score`` is stored in the ``confidence`` column but labeled
    ``score_kind=heuristic`` in provenance — not a calibrated probability.
    Multiple PROPOSED rows per incident are allowed (OPEN ≡ PROPOSED).
    Does not CONFIRM or set LEADING / CAUSED_BY.
    """
    text = statement.strip()
    if not text:
        raise ValueError("hypothesis statement is required")
    if heuristic_score is not None and not (0.0 <= float(heuristic_score) <= 1.0):
        raise ValueError("heuristic_score must be in [0, 1]")

    cited_uuids = resolve_incident_evidence_refs(
        conn, incident_id=incident_id, refs=cited_evidence_ids
    )
    hypothesis_id = uuid4()
    provenance: dict[str, Any] = {
        "writer": "system",
        "proposed_by": proposed_by,
        "score_kind": "heuristic",
        "source": "hypothesis_propose",
    }
    if ai_invocation_id is not None:
        provenance["ai_invocation_id"] = str(ai_invocation_id)
    if heuristic_score is not None:
        provenance["heuristic_score"] = float(heuristic_score)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.hypothesis (
                id, incident_id, status, statement, rationale, hypothesis_class,
                confidence, rank, proposed_by, provenance, cited_evidence_ids
            ) VALUES (
                %s, %s, 'PROPOSED', %s, %s, %s,
                %s, %s, %s, %s::jsonb, %s::uuid[]
            )
            RETURNING id, status, rank, confidence
            """,
            (
                str(hypothesis_id),
                str(incident_id),
                text,
                rationale,
                hypothesis_class,
                float(heuristic_score) if heuristic_score is not None else None,
                rank,
                proposed_by,
                json.dumps(provenance),
                [str(u) for u in cited_uuids],
            ),
        )
        row = cur.fetchone()
        assert row is not None
    if commit:
        conn.commit()
    return ProposeHypothesisResult(
        hypothesis_id=UUID(str(row[0])),
        incident_id=incident_id,
        status=str(row[1]),
        proposed_by=proposed_by,
        heuristic_score=float(row[3]) if row[3] is not None else None,
        cited_evidence_ids=tuple(cited_uuids),
        rank=int(row[2]) if row[2] is not None else None,
    )


def rank_hypotheses_command(
    conn: Connection,
    *,
    incident_id: UUID,
    rankings: list[tuple[UUID, float]] | list[dict[str, Any]],
    commit: bool = True,
) -> RankHypothesesResult:
    """Assign heuristic ranks (1 = best) to PROPOSED hypotheses (H4).

    Does not set LEADING / CONFIRMED. Scores remain labeled heuristic.
    """
    normalized: list[tuple[UUID, float]] = []
    for item in rankings:
        if isinstance(item, dict):
            hid = UUID(str(item["hypothesis_id"]))
            score = float(item["heuristic_score"])
        else:
            hid, score = item
            hid = UUID(str(hid))
            score = float(score)
        if not (0.0 <= score <= 1.0):
            raise ValueError("heuristic_score must be in [0, 1]")
        normalized.append((hid, score))

    # Stable: higher score first → rank 1..N
    ordered = sorted(normalized, key=lambda pair: (-pair[1], str(pair[0])))
    results: list[ProposeHypothesisResult] = []
    with conn.cursor() as cur:
        for rank_i, (hid, score) in enumerate(ordered, start=1):
            cur.execute(
                """
                UPDATE domain.hypothesis
                SET rank = %s,
                    confidence = %s,
                    provenance = provenance || %s::jsonb,
                    updated_at = now()
                WHERE id = %s
                  AND incident_id = %s
                  AND status = 'PROPOSED'
                RETURNING id, status, rank, confidence, proposed_by, cited_evidence_ids
                """,
                (
                    rank_i,
                    score,
                    json.dumps(
                        {
                            "score_kind": "heuristic",
                            "heuristic_score": score,
                            "source": "hypothesis_rank",
                            "writer": "system",
                        }
                    ),
                    str(hid),
                    str(incident_id),
                ),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(
                    f"hypothesis {hid} not found as PROPOSED on incident {incident_id}"
                )
            cited_raw = row[5] or []
            cited = tuple(UUID(str(x)) for x in cited_raw)
            results.append(
                ProposeHypothesisResult(
                    hypothesis_id=UUID(str(row[0])),
                    incident_id=incident_id,
                    status=str(row[1]),
                    proposed_by=str(row[4]),
                    heuristic_score=float(row[3]) if row[3] is not None else None,
                    cited_evidence_ids=cited,
                    rank=int(row[2]) if row[2] is not None else None,
                )
            )
    if commit:
        conn.commit()
    return RankHypothesesResult(incident_id=incident_id, ranked=tuple(results))


def diagnose_incident_command(
    conn: Connection,
    *,
    incident_id: UUID,
    hypothesis_id: UUID,
    expected_revision: int,
    actor: str = "system",
    commit: bool = True,
) -> DiagnoseIncidentResult:
    """SYSTEM gate: mark hypothesis LEADING and transition to DIAGNOSED (H5).

    AI sandbox / non-SYSTEM actors are denied. Generic
    ``transition_incident_command(..., DIAGNOSED)`` is also denied unless it
    passes ``via_diagnose_gate=True`` (only this command sets that).
    """
    if actor not in _DIAGNOSE_ACTORS or actor.startswith("ai_"):
        raise DiagnoseActorDenied(
            f"actor {actor!r} cannot apply LEADING + DIAGNOSED (SYSTEM gate only)"
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, cardinality(cited_evidence_ids)
            FROM domain.hypothesis
            WHERE id = %s AND incident_id = %s
            """,
            (str(hypothesis_id), str(incident_id)),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(
                f"hypothesis {hypothesis_id} not found on incident {incident_id}"
            )
        status, cite_count = str(row[0]), int(row[1] or 0)
        if status != "PROPOSED":
            raise ValueError(
                f"hypothesis {hypothesis_id} status must be PROPOSED to become LEADING "
                f"(got {status})"
            )
        if cite_count < 1:
            raise ValueError("LEADING hypothesis requires at least one evidence citation")

        # Demote any prior LEADING (rare re-diagnose) for audit clarity.
        cur.execute(
            """
            UPDATE domain.hypothesis
            SET status = 'SUPERSEDED',
                updated_at = now(),
                provenance = provenance || %s::jsonb
            WHERE incident_id = %s
              AND status = 'LEADING'
            """,
            (
                json.dumps({"writer": "system", "source": "hypothesis_leading_supersede"}),
                str(incident_id),
            ),
        )
        cur.execute(
            """
            UPDATE domain.hypothesis
            SET status = 'LEADING',
                leading_at = now(),
                updated_at = now(),
                provenance = provenance || %s::jsonb
            WHERE id = %s
              AND incident_id = %s
            RETURNING leading_at
            """,
            (
                json.dumps(
                    {
                        "writer": "system",
                        "source": "hypothesis_leading",
                        "score_kind": "heuristic",
                    }
                ),
                str(hypothesis_id),
                str(incident_id),
            ),
        )
        leading_row = cur.fetchone()
        assert leading_row is not None
        leading_at = leading_row[0]
        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (
                %s, 'HYPOTHESIS_LEADING', %s, %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                f"hypothesis {hypothesis_id} designated LEADING",
                actor,
                json.dumps({"hypothesis_id": str(hypothesis_id)}),
            ),
        )

    transition = transition_incident_command(
        conn,
        incident_id=incident_id,
        expected_revision=expected_revision,
        to_state=IncidentState.DIAGNOSED,
        actor=actor,
        commit=False,
        via_diagnose_gate=True,
    )
    if commit:
        conn.commit()
    return DiagnoseIncidentResult(
        incident_id=incident_id,
        hypothesis_id=hypothesis_id,
        leading_at=leading_at,
        from_state=transition.from_state.value,
        to_state=transition.to_state.value,
        previous_revision=transition.previous_revision,
        new_revision=transition.new_revision,
    )


def create_runbook_command(
    conn: Connection,
    *,
    key: str,
    title: str,
    hypothesis_class: str | None = None,
    description: str | None = None,
    service_key: str | None = None,
    environment: str = "local",
    commit: bool = True,
) -> CreateRunbookResult:
    """Create a logical runbook (H6)."""
    rb_key = key.strip()
    if not rb_key:
        raise ValueError("runbook key is required")
    title_s = title.strip()
    if not title_s:
        raise ValueError("runbook title is required")
    service_id: UUID | None = None
    if service_key and service_key.strip():
        service_id = _ensure_service_id(
            conn, service_key=service_key.strip(), environment=environment
        )
    runbook_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.runbook (
                id, key, title, service_id, hypothesis_class, description
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, key
            """,
            (
                str(runbook_id),
                rb_key,
                title_s,
                str(service_id) if service_id else None,
                hypothesis_class,
                description,
            ),
        )
        row = cur.fetchone()
        assert row is not None
    if commit:
        conn.commit()
    return CreateRunbookResult(runbook_id=UUID(str(row[0])), key=str(row[1]))


def create_runbook_version_command(
    conn: Connection,
    *,
    runbook_id: UUID,
    body_markdown: str,
    allowed_action_types: list[str] | tuple[str, ...],
    version: int | None = None,
    proposed_by: str = "system",
    commit: bool = True,
) -> CreateRunbookVersionResult:
    """Create a draft RunbookVersion. Authority is ``allowed_action_types`` only."""
    actions = tuple(str(a).strip() for a in allowed_action_types if str(a).strip())
    if not actions:
        raise ValueError("allowed_action_types must be non-empty (prose is not authority)")
    body = body_markdown if body_markdown is not None else ""
    with conn.cursor() as cur:
        if version is None:
            cur.execute(
                """
                SELECT COALESCE(MAX(version), 0) + 1
                FROM domain.runbook_version
                WHERE runbook_id = %s
                """,
                (str(runbook_id),),
            )
            next_version = int(cur.fetchone()[0])
        else:
            next_version = int(version)
        version_id = uuid4()
        cur.execute(
            """
            INSERT INTO domain.runbook_version (
                id, runbook_id, version, status, body_markdown,
                allowed_action_types, proposed_by
            ) VALUES (
                %s, %s, %s, 'draft', %s, %s::text[], %s
            )
            RETURNING id, version, status, allowed_action_types
            """,
            (
                str(version_id),
                str(runbook_id),
                next_version,
                body,
                list(actions),
                proposed_by,
            ),
        )
        row = cur.fetchone()
        assert row is not None
    if commit:
        conn.commit()
    allowed = tuple(str(x) for x in (row[3] or []))
    return CreateRunbookVersionResult(
        runbook_version_id=UUID(str(row[0])),
        runbook_id=runbook_id,
        version=int(row[1]),
        status=str(row[2]),
        allowed_action_types=allowed,
    )


def publish_runbook_version_command(
    conn: Connection,
    *,
    runbook_version_id: UUID,
    set_active: bool = True,
    commit: bool = True,
) -> CreateRunbookVersionResult:
    """Publish a draft version (immutable thereafter) and optionally set active."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT runbook_id, version, status, allowed_action_types
            FROM domain.runbook_version
            WHERE id = %s
            """,
            (str(runbook_version_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"runbook_version not found: {runbook_version_id}")
        runbook_id = UUID(str(row[0]))
        version = int(row[1])
        status = str(row[2])
        allowed = tuple(str(x) for x in (row[3] or []))
        if status == "published":
            return CreateRunbookVersionResult(
                runbook_version_id=runbook_version_id,
                runbook_id=runbook_id,
                version=version,
                status=status,
                allowed_action_types=allowed,
            )
        if status != "draft":
            raise ValueError(f"cannot publish runbook_version in status {status}")
        cur.execute(
            """
            UPDATE domain.runbook_version
            SET status = 'published'
            WHERE id = %s
            RETURNING status, allowed_action_types
            """,
            (str(runbook_version_id),),
        )
        published = cur.fetchone()
        assert published is not None
        if set_active:
            cur.execute(
                """
                UPDATE domain.runbook
                SET active_version_id = %s, updated_at = now()
                WHERE id = %s
                """,
                (str(runbook_version_id), str(runbook_id)),
            )
    if commit:
        conn.commit()
    return CreateRunbookVersionResult(
        runbook_version_id=runbook_version_id,
        runbook_id=runbook_id,
        version=version,
        status=str(published[0]),
        allowed_action_types=tuple(str(x) for x in (published[1] or [])),
    )


def pin_runbook_version_command(
    conn: Connection,
    *,
    incident_id: UUID,
    runbook_version_id: UUID,
    actor: str = "system",
    commit: bool = True,
) -> PinRunbookResult:
    """Pin a published RunbookVersion on an incident and emit RUNBOOK_FACT (H6).

    Authority for later ProposeAction is ``allowed_action_types`` in the fact
    payload — never ``body_markdown``.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rv.status, rv.version, rv.allowed_action_types, r.key, r.hypothesis_class
            FROM domain.runbook_version rv
            JOIN domain.runbook r ON r.id = rv.runbook_id
            WHERE rv.id = %s
            """,
            (str(runbook_version_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"runbook_version not found: {runbook_version_id}")
        status = str(row[0])
        if status != "published":
            raise ValueError(f"only published versions can be pinned (got {status})")
        version = int(row[1])
        allowed = tuple(str(x) for x in (row[2] or []))
        runbook_key = str(row[3])
        hypothesis_class = str(row[4]) if row[4] is not None else None
        if not allowed:
            raise ValueError("pinned version has empty allowed_action_types")

        cur.execute(
            """
            UPDATE domain.incident
            SET pinned_runbook_version_id = %s
            WHERE id = %s
            RETURNING id
            """,
            (str(runbook_version_id), str(incident_id)),
        )
        if cur.fetchone() is None:
            raise ValueError(f"incident not found: {incident_id}")

        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (
                %s, 'RUNBOOK_PINNED', %s, %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                f"pinned {runbook_key}@v{version}",
                actor,
                json.dumps(
                    {
                        "runbook_version_id": str(runbook_version_id),
                        "runbook_key": runbook_key,
                        "version": version,
                        "allowed_action_types": list(allowed),
                    }
                ),
            ),
        )

    fact = append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="RUNBOOK_FACT",
        fingerprint=f"runbook_store:pin:{incident_id}:{runbook_version_id}",
        summary=f"Pinned runbook {runbook_key} v{version}",
        payload={
            "runbook_version_id": str(runbook_version_id),
            "runbook_key": runbook_key,
            "version": version,
            "allowed_action_types": list(allowed),
            "hypothesis_class": hypothesis_class,
            # Explicit: prose is not authority.
            "authority": "allowed_action_types",
        },
        provenance={"writer": "system", "source": "runbook_pin", "actor": actor},
        producer="runbook_store",
        commit=False,
    )
    if commit:
        conn.commit()
    return PinRunbookResult(
        incident_id=incident_id,
        runbook_version_id=runbook_version_id,
        evidence_id=fact.evidence_id,
        evidence_key=fact.evidence_key,
        allowed_action_types=allowed,
    )


def record_impact_snapshot_command(
    conn: Connection,
    *,
    incident_id: UUID,
    cited_evidence_ids: list[str] | tuple[str, ...],
    severity: str | None = None,
    customer_impact_summary: str | None = None,
    estimated_affected_users: int | None = None,
    metrics: dict[str, Any] | None = None,
    quality_rule_id: str = "impact_from_metrics.v1",
    commit: bool = True,
) -> RecordImpactSnapshotResult:
    """SYSTEM insert of an impact snapshot citing Evidence (H7)."""
    cited = resolve_incident_evidence_refs(
        conn, incident_id=incident_id, refs=cited_evidence_ids
    )
    snapshot_id = uuid4()
    provenance = {
        "writer": "system",
        "source": "impact_calculator",
        "quality_rule_id": quality_rule_id,
        "cited_evidence_ids": [str(u) for u in cited],
        "cited_evidence_keys": list(cited_evidence_ids),
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.impact_snapshot (
                id, incident_id, severity, customer_impact_summary,
                estimated_affected_users, metrics, provenance
            ) VALUES (
                %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb
            )
            RETURNING id
            """,
            (
                str(snapshot_id),
                str(incident_id),
                severity,
                customer_impact_summary,
                estimated_affected_users,
                json.dumps(metrics or {}),
                json.dumps(provenance),
            ),
        )
        row = cur.fetchone()
        assert row is not None
    if commit:
        conn.commit()
    return RecordImpactSnapshotResult(
        snapshot_id=UUID(str(row[0])),
        incident_id=incident_id,
        severity=severity,
        estimated_affected_users=estimated_affected_users,
        cited_evidence_ids=tuple(cited),
    )


def record_slo_burn_command(
    conn: Connection,
    *,
    incident_id: UUID,
    cited_evidence_ids: list[str] | tuple[str, ...],
    slo_key: str,
    window_label: str,
    burn_rate: float | None = None,
    error_budget_remaining: float | None = None,
    payload: dict[str, Any] | None = None,
    service_id: UUID | None = None,
    quality_rule_id: str = "slo_burn_from_metrics.v1",
    commit: bool = True,
) -> RecordSloBurnResult:
    """SYSTEM insert of an SLO burn observation citing Evidence (H7)."""
    cited = resolve_incident_evidence_refs(
        conn, incident_id=incident_id, refs=cited_evidence_ids
    )
    burn_id = uuid4()
    provenance = {
        "writer": "system",
        "source": "slo_burn_calculator",
        "quality_rule_id": quality_rule_id,
        "cited_evidence_ids": [str(u) for u in cited],
        "cited_evidence_keys": list(cited_evidence_ids),
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.slo_burn (
                id, incident_id, service_id, slo_key, window_label,
                burn_rate, error_budget_remaining, payload, provenance
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb
            )
            RETURNING id
            """,
            (
                str(burn_id),
                str(incident_id),
                str(service_id) if service_id else None,
                slo_key,
                window_label,
                burn_rate,
                error_budget_remaining,
                json.dumps(payload or {}),
                json.dumps(provenance),
            ),
        )
        row = cur.fetchone()
        assert row is not None
    if commit:
        conn.commit()
    return RecordSloBurnResult(
        slo_burn_id=UUID(str(row[0])),
        incident_id=incident_id,
        slo_key=slo_key,
        window_label=window_label,
        burn_rate=burn_rate,
        error_budget_remaining=error_budget_remaining,
        cited_evidence_ids=tuple(cited),
    )


def compute_impact_snapshot_command(
    conn: Connection,
    *,
    incident_id: UUID,
    commit: bool = True,
) -> RecordImpactSnapshotResult:
    """Load METRIC evidence for the incident, compute heuristic impact, persist."""
    from incidentpilot_shared.processors.impact import impact_from_metrics

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT evidence_key, payload
            FROM domain.evidence
            WHERE incident_id = %s AND kind = 'METRIC'
            ORDER BY observed_at DESC
            LIMIT 20
            """,
            (str(incident_id),),
        )
        rows = cur.fetchall()
    if not rows:
        raise ValueError("no METRIC evidence on incident for impact snapshot")
    keys: list[str] = []
    payloads: list[dict[str, Any]] = []
    for key, payload in rows:
        keys.append(str(key))
        if isinstance(payload, dict):
            payloads.append(payload)
        else:
            payloads.append(json.loads(payload) if payload else {})
    estimate = impact_from_metrics(payloads)
    if estimate is None:
        raise ValueError("impact calculator produced no estimate from METRIC evidence")
    return record_impact_snapshot_command(
        conn,
        incident_id=incident_id,
        cited_evidence_ids=keys,
        severity=estimate.severity,
        customer_impact_summary=estimate.customer_impact_summary,
        estimated_affected_users=estimate.estimated_affected_users,
        metrics=estimate.metrics,
        quality_rule_id=estimate.quality_rule_id,
        commit=commit,
    )


def compute_slo_burn_command(
    conn: Connection,
    *,
    incident_id: UUID,
    slo_key: str = "checkout_availability",
    window_label: str = "1h",
    slo_target: float = 0.999,
    commit: bool = True,
) -> RecordSloBurnResult:
    """Load latest METRIC evidence, compute SLO burn, persist."""
    from incidentpilot_shared.processors.impact import slo_burn_from_metrics

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT evidence_key, payload
            FROM domain.evidence
            WHERE incident_id = %s AND kind = 'METRIC'
            ORDER BY observed_at DESC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError("no METRIC evidence on incident for SLO burn")
    key = str(row[0])
    payload = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
    estimate = slo_burn_from_metrics(
        payload, slo_key=slo_key, window_label=window_label, slo_target=slo_target
    )
    if estimate is None:
        raise ValueError("SLO burn calculator produced no estimate")
    return record_slo_burn_command(
        conn,
        incident_id=incident_id,
        cited_evidence_ids=[key],
        slo_key=estimate.slo_key,
        window_label=estimate.window_label,
        burn_rate=estimate.burn_rate,
        error_budget_remaining=estimate.error_budget_remaining,
        payload=estimate.payload,
        quality_rule_id=estimate.quality_rule_id,
        commit=commit,
    )


def update_incident_severity_command(
    conn: Connection,
    *,
    incident_id: UUID,
    actor: str = "system",
    commit: bool = True,
) -> UpdateIncidentSeverityResult:
    """SYSTEM rules: set ``incident.severity`` from hint + impact/SLO/criticality (H8).

    AI sandbox / non-SYSTEM actors are denied. There is no AI tool to set severity.
    """
    if actor not in _SEVERITY_ACTORS or actor.startswith("ai_"):
        raise SeverityActorDenied(
            f"actor {actor!r} cannot set incident severity (SYSTEM rules only)"
        )

    from incidentpilot_shared.processors.severity import severity_from_signals

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT severity
            FROM domain.incident
            WHERE id = %s
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"incident {incident_id} not found")
        previous = None if row[0] is None else str(row[0])

        # Hint: latest firing alert label, else current severity (create-time hint).
        cur.execute(
            """
            SELECT labels
            FROM domain.alert
            WHERE incident_id = %s
            ORDER BY received_at DESC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        alert_row = cur.fetchone()
        hint = previous
        if alert_row is not None:
            raw_labels = alert_row[0]
            if isinstance(raw_labels, dict):
                labels = raw_labels
            else:
                labels = json.loads(raw_labels or "{}")
            if isinstance(labels, dict):
                for key in ("severity", "severity_hint", "sev"):
                    if labels.get(key):
                        hint = str(labels[key])
                        break

        cur.execute(
            """
            SELECT severity
            FROM domain.impact_snapshot
            WHERE incident_id = %s
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        snap = cur.fetchone()
        impact_severity = None if snap is None or snap[0] is None else str(snap[0])

        cur.execute(
            """
            SELECT burn_rate, error_budget_remaining
            FROM domain.slo_burn
            WHERE incident_id = %s
            ORDER BY observed_at DESC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        burn_row = cur.fetchone()
        burn_rate = None if burn_row is None else (
            float(burn_row[0]) if burn_row[0] is not None else None
        )
        budget = None if burn_row is None else (
            float(burn_row[1]) if burn_row[1] is not None else None
        )

        # Highest criticality among linked services (default MEDIUM).
        cur.execute(
            """
            SELECT COALESCE(MAX(
                CASE s.criticality
                    WHEN 'CRITICAL' THEN 3
                    WHEN 'HIGH' THEN 2
                    WHEN 'MEDIUM' THEN 1
                    WHEN 'LOW' THEN 0
                    ELSE 1
                END
            ), 1) AS crit_rank
            FROM domain.incident_service isv
            JOIN domain.service s ON s.id = isv.service_id
            WHERE isv.incident_id = %s
            """,
            (str(incident_id),),
        )
        crit_row = cur.fetchone()
        crit_rank = int(crit_row[0]) if crit_row is not None else 1
        criticality = {3: "CRITICAL", 2: "HIGH", 1: "MEDIUM", 0: "LOW"}[crit_rank]

    decision = severity_from_signals(
        severity_hint=hint,
        impact_severity=impact_severity,
        burn_rate=burn_rate,
        error_budget_remaining=budget,
        criticality=criticality,
    )
    changed = previous != decision.severity

    with conn.cursor() as cur:
        if changed:
            cur.execute(
                """
                UPDATE domain.incident
                SET severity = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (decision.severity, str(incident_id)),
            )
        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (
                %s, 'SEVERITY_UPDATE', %s, %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                (
                    f"severity {previous} → {decision.severity}"
                    if changed
                    else f"severity unchanged ({decision.severity})"
                ),
                actor,
                json.dumps(
                    {
                        "previous": previous,
                        "severity": decision.severity,
                        "changed": changed,
                        "explanation": decision.explanation,
                        "quality_rule_id": decision.quality_rule_id,
                        "inputs": decision.inputs,
                    }
                ),
            ),
        )
        cur.execute(
            """
            INSERT INTO domain.audit_event (
                incident_id, action, actor, resource_type, resource_id, details
            ) VALUES (
                %s, 'incident.severity_update', %s, 'incident', %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                actor,
                str(incident_id),
                json.dumps(
                    {
                        "previous": previous,
                        "severity": decision.severity,
                        "changed": changed,
                        "quality_rule_id": decision.quality_rule_id,
                    }
                ),
            ),
        )
    if commit:
        conn.commit()
    return UpdateIncidentSeverityResult(
        incident_id=incident_id,
        previous_severity=previous,
        severity=decision.severity,
        changed=changed,
        explanation=decision.explanation,
        quality_rule_id=decision.quality_rule_id,
        inputs=decision.inputs,
    )

