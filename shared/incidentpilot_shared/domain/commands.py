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
    IllegalTransitionError,
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
class CreateApprovalResult:
    approval_id: UUID
    action_id: UUID
    action_version: int
    status: str
    action_status: str
    inserted: bool


@dataclass(frozen=True, slots=True)
class ApprovalDecisionResult:
    approval_id: UUID
    status: str
    action_id: UUID
    action_version: int
    action_status: str
    decided_by: str | None
    noop: bool = False


@dataclass(frozen=True, slots=True)
class ConsumeApprovalResult:
    approval_id: UUID
    action_id: UUID
    action_version: int
    status: str
    noop: bool = False


class StaleActionVersion(Exception):
    """Requested action_version is not authorized by the bound Approval."""

    code = "STALE_ACTION_VERSION"

    def __init__(self, message: str = "STALE_ACTION_VERSION") -> None:
        super().__init__(message)


class ApprovalPolicyRequired(Exception):
    """Approval create requires REQUIRE_APPROVAL PolicyDecision for that version."""


class ApprovalNotConsumable(Exception):
    """Approval is not in APPROVED (or already CONSUMED) state for consume."""


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
    artifact_uri: str | None = None
    input_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CreatePostmortemDraftResult:
    postmortem_id: UUID
    incident_id: UUID
    status: str
    title: str
    claim_count: int
    cited_evidence_ids: tuple[UUID, ...]
    inserted: bool


class PostmortemNotReadyError(ValueError):
    """Raised when draft is requested before the incident is RESOLVED (L4)."""


class PostmortemFinalImmutableError(ValueError):
    """Raised when attempting to rewrite a FINAL postmortem."""


class PostmortemFinalRequiredError(ValueError):
    """Raised when CLOSED is requested without a FINAL postmortem (L5)."""


class PostmortemCorrectiveActionsError(ValueError):
    """Raised when FINAL lacks a valid corrective_actions[] (L5)."""


@dataclass(frozen=True, slots=True)
class FinalizePostmortemResult:
    postmortem_id: UUID
    incident_id: UUID
    status: str
    corrective_actions: tuple[dict[str, Any], ...]
    incident_state: str
    incident_revision: int


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
class ConfirmHypothesisResult:
    incident_id: UUID
    hypothesis_id: UUID
    status: str
    hypothesis_class: str | None
    caused_by_written: bool
    reason: str
    quality_rule_id: str
    inputs: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProposeActionResult:
    action_id: UUID
    incident_id: UUID
    action_type: str
    version: int
    current_version: int
    status: str
    parameters: dict[str, Any]
    runbook_version_id: UUID
    allowed_action_types: tuple[str, ...]
    bumped: bool
    is_reversible: bool
    reverse_action_type: str | None
    compensates_action_id: UUID | None = None
    compensates_action_version: int | None = None


@dataclass(frozen=True, slots=True)
class EvaluatePolicyResult:
    policy_decision_id: UUID
    action_id: UUID
    action_version: int
    incident_id: UUID
    decision: str
    reason: str
    policy_key: str
    policy_version: str
    action_status: str
    autonomy_level: int
    autonomy_source: str


@dataclass(frozen=True, slots=True)
class PolicyDefinitionResult:
    policy_definition_id: UUID
    policy_key: str
    version: int
    version_label: str
    body: dict[str, Any]
    notes: str | None
    created_by: str
    active: bool


@dataclass(frozen=True, slots=True)
class ActivatePolicyResult:
    policy_key: str
    version: int
    version_label: str
    activated_by: str


@dataclass(frozen=True, slots=True)
class UpsertAutonomyConfigResult:
    config_id: UUID
    service_key: str | None
    action_type: str | None
    environment: str | None
    severity: str | None
    autonomy_level: int
    notes: str | None
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

# H5: DIAGNOSED is a SYSTEM gate — not free-form TransitionIncident.
_DIAGNOSE_ACTORS = frozenset({"system", "incident-workflow"})
# H8: incident.severity is SYSTEM-rules only (AI explains, never sets).
_SEVERITY_ACTORS = frozenset({"system", "incident-workflow"})
# H10: CONFIRM / CAUSED_BY are SYSTEM confirmation rules only.
_CONFIRM_ACTORS = frozenset({"system", "incident-workflow"})
# I2: EvaluatePolicy is SYSTEM-only (AI never binds POLICY_EVAL).
_POLICY_ACTORS = frozenset({"system", "incident-workflow"})


class DiagnosedGateError(PermissionError):
    """Raised when DIAGNOSED is requested outside ``diagnose_incident_command``."""


class DiagnoseActorDenied(PermissionError):
    """Raised when a non-SYSTEM actor attempts the LEADING + DIAGNOSED gate."""


class SeverityActorDenied(PermissionError):
    """Raised when a non-SYSTEM actor attempts to set incident severity."""


class ConfirmActorDenied(PermissionError):
    """Raised when a non-SYSTEM actor attempts hypothesis CONFIRM (H10)."""


class ConfirmationRulesNotMet(ValueError):
    """Raised when class confirmation rules reject CONFIRM."""


class ActionTypeNotAllowed(ValueError):
    """Raised when ProposeAction type is outside pinned runbook allowlist (I1)."""


class PinnedRunbookRequired(ValueError):
    """Raised when ProposeAction runs without a pinned RunbookVersion."""


class PolicyActorDenied(PermissionError):
    """Raised when a non-SYSTEM actor attempts EvaluatePolicy (I2)."""


class PolicyDecisionExists(ValueError):
    """Raised when a PolicyDecision already exists for (action_id, version)."""


_KNOWN_ACTION_TYPES = frozenset(
    {
        "ROLLBACK_DEPLOYMENT",
        "RESTART_WORKLOAD",
        "SCALE_WORKLOAD",
        "DISABLE_FEATURE_FLAG",
        "RESTORE_FEATURE_FLAG",
        "RESTORE_CONFIG",
        "PAUSE_CONSUMER",
        "REROUTE_TRAFFIC",
        "OTHER",
    }
)


def _default_reversibility(action_type: str) -> tuple[bool, str | None]:
    if action_type == "ROLLBACK_DEPLOYMENT":
        return True, "OTHER"
    if action_type == "DISABLE_FEATURE_FLAG":
        return True, "RESTORE_FEATURE_FLAG"
    if action_type == "RESTORE_FEATURE_FLAG":
        return True, "DISABLE_FEATURE_FLAG"
    if action_type == "RESTORE_CONFIG":
        return True, "OTHER"
    if action_type == "PAUSE_CONSUMER":
        return True, "OTHER"
    if action_type == "REROUTE_TRAFFIC":
        return True, "REROUTE_TRAFFIC"
    return False, None


class CompensationParentRequired(ValueError):
    """Compensation must reference a parent Action version."""


class CompensationActionTypeRequired(ValueError):
    """Parent has no usable reverse_action_type; caller must pass action_type."""


class ParentApprovalReuseDenied(PermissionError):
    """Parent Approval/PolicyDecision cannot authorize a compensation Action (J9)."""


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
    Replan paths (e.g. ``AWAITING_APPROVAL → DIAGNOSED`` on I5 timeout) are
    allowed without the diagnose gate.

    ``POSTMORTEM → CLOSED`` requires a FINAL postmortem (L5) — no skip.
    """
    target = IncidentState(to_state) if not isinstance(to_state, IncidentState) else to_state
    if target is IncidentState.DIAGNOSED and not via_diagnose_gate:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM domain.incident WHERE id = %s",
                (str(incident_id),),
            )
            row = cur.fetchone()
            current = IncidentState(row[0]) if row is not None else None
        if current is IncidentState.INVESTIGATING:
            raise DiagnosedGateError(
                "DIAGNOSED is only allowed via diagnose_incident_command (SYSTEM gate)"
            )
    if target is IncidentState.CLOSED:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM domain.incident WHERE id = %s",
                (str(incident_id),),
            )
            inc_row = cur.fetchone()
            current_for_close = (
                IncidentState(inc_row[0]) if inc_row is not None else None
            )
            if current_for_close is IncidentState.POSTMORTEM:
                cur.execute(
                    """
                    SELECT status FROM domain.postmortem
                    WHERE incident_id = %s
                    """,
                    (str(incident_id),),
                )
                pm = cur.fetchone()
                if pm is None or str(pm[0]) != "FINAL":
                    raise PostmortemFinalRequiredError(
                        "CLOSED requires a FINAL postmortem "
                        "(RESOLVED→POSTMORTEM→FINAL→CLOSED)"
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


class CausedByActorDenied(PermissionError):
    """Raised when a non-SYSTEM path attempts to write CAUSED_BY (H10)."""


def link_evidence_relation_command(
    conn: Connection,
    *,
    from_evidence_id: UUID,
    to_evidence_id: UUID,
    relation_type: str,
    commit: bool = True,
    via_confirmation_gate: bool = False,
) -> None:
    """Insert an evidence graph edge (idempotent on unique triple).

    ``CAUSED_BY`` is SYSTEM-only under confirmation rules (H10) — humans/AI
    cannot write it directly; only ``confirm_hypothesis_command`` sets
    ``via_confirmation_gate=True``.
    """
    allowed = {
        "SUPPORTS",
        "CONTRADICTS",
        "DERIVED_FROM",
        "SAME_SIGNAL",
        "TEMPORAL_NEAR",
        "CAUSED_BY",
    }
    if relation_type not in allowed:
        raise ValueError(f"invalid evidence relation_type: {relation_type!r}")
    if relation_type == "CAUSED_BY" and not via_confirmation_gate:
        raise CausedByActorDenied(
            "CAUSED_BY may only be written by SYSTEM confirmation rules (H10)"
        )
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


def create_approval_command(
    conn: Connection,
    *,
    action_id: UUID,
    action_version: int | None = None,
    expires_at: datetime | None = None,
    commit: bool = True,
) -> CreateApprovalResult:
    """Create PENDING Approval bound to an exact action_version (I4).

    Requires PolicyDecision = REQUIRE_APPROVAL for that version. Duplicate
    create for the same ``(action_id, action_version)`` is a safe no-op.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.incident_id, a.current_version, a.status
            FROM domain.action a
            WHERE a.id = %s
            """,
            (str(action_id),),
        )
        action_row = cur.fetchone()
        if action_row is None:
            raise LookupError(f"action {action_id} not found")
        incident_id = UUID(str(action_row[0]))
        current_version = int(action_row[1])
        version = int(action_version) if action_version is not None else current_version

        cur.execute(
            """
            SELECT 1 FROM domain.action_version
            WHERE action_id = %s AND version = %s
            """,
            (str(action_id), version),
        )
        if cur.fetchone() is None:
            raise LookupError(f"action_version {action_id} v{version} not found")

        cur.execute(
            """
            SELECT decision FROM domain.policy_decision
            WHERE action_id = %s AND action_version = %s
            """,
            (str(action_id), version),
        )
        policy_row = cur.fetchone()
        if policy_row is None or str(policy_row[0]) != "REQUIRE_APPROVAL":
            raise ApprovalPolicyRequired(
                f"REQUIRE_APPROVAL PolicyDecision required to create approval "
                f"for action {action_id} v{version}"
            )

        cur.execute(
            """
            SELECT id, status FROM domain.approval
            WHERE action_id = %s AND action_version = %s
            """,
            (str(action_id), version),
        )
        existing = cur.fetchone()
        if existing is not None:
            if commit:
                conn.commit()
            return CreateApprovalResult(
                approval_id=UUID(str(existing[0])),
                action_id=action_id,
                action_version=version,
                status=str(existing[1]),
                action_status="AWAITING_APPROVAL"
                if str(existing[1]) == "PENDING"
                else str(action_row[2]),
                inserted=False,
            )

        approval_id = uuid4()
        cur.execute(
            """
            INSERT INTO domain.approval (
                id, action_id, action_version, status, expires_at
            ) VALUES (%s, %s, %s, 'PENDING', %s)
            """,
            (str(approval_id), str(action_id), version, expires_at),
        )
        cur.execute(
            """
            UPDATE domain.action
            SET status = 'AWAITING_APPROVAL', updated_at = now()
            WHERE id = %s
            """,
            (str(action_id),),
        )
        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (
                %s, 'APPROVAL_CREATED', %s, 'system', %s::jsonb
            )
            """,
            (
                str(incident_id),
                f"approval pending for action {action_id} v{version}",
                json.dumps(
                    {
                        "approval_id": str(approval_id),
                        "action_id": str(action_id),
                        "action_version": version,
                    }
                ),
            ),
        )
    if commit:
        conn.commit()
    return CreateApprovalResult(
        approval_id=approval_id,
        action_id=action_id,
        action_version=version,
        status="PENDING",
        action_status="AWAITING_APPROVAL",
        inserted=True,
    )


def decide_approval_command(
    conn: Connection,
    *,
    action_id: UUID,
    action_version: int,
    status: str,
    decided_by: str,
    commit: bool = True,
) -> ApprovalDecisionResult:
    """Record human/harness approval decision for a bound action version (I4).

    Duplicate decide with the same status is a safe no-op. Reject is visible:
    approval → REJECTED and action → CANCELLED.
    """
    if status not in {"APPROVED", "REJECTED"}:
        raise ValueError("status must be APPROVED or REJECTED")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, decided_by
            FROM domain.approval
            WHERE action_id = %s AND action_version = %s
            """,
            (str(action_id), action_version),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"no approval for action {action_id} v{action_version}")
        approval_id = UUID(str(row[0]))
        current_status = str(row[1])
        prior_decided_by = None if row[2] is None else str(row[2])

        if current_status == status:
            cur.execute(
                "SELECT status FROM domain.action WHERE id = %s",
                (str(action_id),),
            )
            action_row = cur.fetchone()
            action_status = str(action_row[0]) if action_row is not None else "UNKNOWN"
            if commit:
                conn.commit()
            return ApprovalDecisionResult(
                approval_id=approval_id,
                status=status,
                action_id=action_id,
                action_version=action_version,
                action_status=action_status,
                decided_by=prior_decided_by or decided_by,
                noop=True,
            )

        if current_status != "PENDING":
            raise LookupError(
                f"approval for action {action_id} v{action_version} "
                f"is {current_status}, not PENDING"
            )

        action_status = "APPROVED" if status == "APPROVED" else "CANCELLED"
        cur.execute(
            """
            UPDATE domain.approval
            SET status = %s,
                decided_by = %s,
                decided_at = now()
            WHERE id = %s AND status = 'PENDING'
            RETURNING id
            """,
            (status, decided_by, str(approval_id)),
        )
        if cur.fetchone() is None:
            raise LookupError(f"no PENDING approval for action {action_id} v{action_version}")
        cur.execute(
            """
            UPDATE domain.action
            SET status = %s, updated_at = now()
            WHERE id = %s
            """,
            (action_status, str(action_id)),
        )
        cur.execute(
            """
            SELECT incident_id FROM domain.action WHERE id = %s
            """,
            (str(action_id),),
        )
        incident_row = cur.fetchone()
        incident_id: UUID | None = (
            UUID(str(incident_row[0])) if incident_row is not None else None
        )
        if incident_id is not None:
            cur.execute(
                """
                INSERT INTO domain.timeline_event (
                    incident_id, event_type, summary, actor, payload
                ) VALUES (
                    %s, %s, %s, %s, %s::jsonb
                )
                """,
                (
                    str(incident_id),
                    "APPROVAL_DECIDED",
                    f"approval {status} for action {action_id} v{action_version}",
                    decided_by,
                    json.dumps(
                        {
                            "approval_id": str(approval_id),
                            "action_id": str(action_id),
                            "action_version": action_version,
                            "status": status,
                            "action_status": action_status,
                        }
                    ),
                ),
            )
            # I5: wake IncidentWorkflow approval wait (outbox → signal).
            from incidentpilot_shared.domain.outbox import enqueue_outbox

            enqueue_outbox(
                conn,
                aggregate_type="incident",
                aggregate_id=str(incident_id),
                event_type="approval.decided",
                payload={
                    "approval_id": str(approval_id),
                    "action_id": str(action_id),
                    "action_version": action_version,
                    "status": status,
                    "decided_by": decided_by,
                },
            )

    if incident_id is not None:
        from incidentpilot_shared.audit import append_audit_event

        append_audit_event(
            conn,
            incident_id=incident_id,
            action="approval.decide",
            actor=decided_by,
            resource_type="approval",
            resource_id=str(approval_id),
            outcome="success",
            details={
                "approval_id": str(approval_id),
                "action_id": str(action_id),
                "action_version": action_version,
                "status": status,
                "action_status": action_status,
            },
        )

    if commit:
        conn.commit()
    return ApprovalDecisionResult(
        approval_id=approval_id,
        status=status,
        action_id=action_id,
        action_version=action_version,
        action_status=action_status,
        decided_by=decided_by,
        noop=False,
    )


@dataclass(frozen=True, slots=True)
class ExpireApprovalsResult:
    incident_id: UUID
    expired_count: int
    action_ids: tuple[UUID, ...]


def expire_pending_approvals_command(
    conn: Connection,
    *,
    incident_id: UUID,
    reason: str = "approval_timeout",
    commit: bool = True,
) -> ExpireApprovalsResult:
    """Mark PENDING approvals EXPIRED for an incident (I5 timeout; no execute)."""
    expired: list[UUID] = []
    action_ids: list[UUID] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ap.id, ap.action_id
            FROM domain.approval ap
            JOIN domain.action a ON a.id = ap.action_id
            WHERE a.incident_id = %s
              AND ap.status = 'PENDING'
            FOR UPDATE OF ap
            """,
            (str(incident_id),),
        )
        rows = cur.fetchall()
        for row in rows:
            approval_id = UUID(str(row[0]))
            action_id = UUID(str(row[1]))
            cur.execute(
                """
                UPDATE domain.approval
                SET status = 'EXPIRED', decided_at = now(),
                    decided_by = 'system:approval_timeout'
                WHERE id = %s AND status = 'PENDING'
                """,
                (str(approval_id),),
            )
            if cur.rowcount == 1:
                expired.append(approval_id)
                action_ids.append(action_id)
                cur.execute(
                    """
                    UPDATE domain.action
                    SET status = 'CANCELLED', updated_at = now()
                    WHERE id = %s AND status = 'AWAITING_APPROVAL'
                    """,
                    (str(action_id),),
                )
        if expired:
            cur.execute(
                """
                INSERT INTO domain.timeline_event (
                    incident_id, event_type, summary, actor, payload
                ) VALUES (
                    %s, 'APPROVAL_TIMEOUT', %s, 'system', %s::jsonb
                )
                """,
                (
                    str(incident_id),
                    f"approval timeout expired {len(expired)} pending approval(s)",
                    json.dumps(
                        {
                            "reason": reason,
                            "expired_approval_ids": [str(x) for x in expired],
                            "action_ids": [str(x) for x in action_ids],
                            "remediation_executed": False,
                        }
                    ),
                ),
            )
    if commit:
        conn.commit()
    return ExpireApprovalsResult(
        incident_id=incident_id,
        expired_count=len(expired),
        action_ids=tuple(action_ids),
    )


def consume_approval_command(
    conn: Connection,
    *,
    action_id: UUID,
    action_version: int,
    commit: bool = True,
) -> ConsumeApprovalResult:
    """Single-use consume of an APPROVED approval for an exact version (I4).

    vN approval cannot authorize vM (M≠N) — raises ``StaleActionVersion``
    (``STALE_ACTION_VERSION``). Already-CONSUMED is a safe no-op.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status FROM domain.approval
            WHERE action_id = %s AND action_version = %s
            """,
            (str(action_id), action_version),
        )
        row = cur.fetchone()
        if row is None:
            raise StaleActionVersion(
                f"STALE_ACTION_VERSION: no approval for action {action_id} v{action_version}"
            )
        approval_id = UUID(str(row[0]))
        current_status = str(row[1])

        if current_status == "CONSUMED":
            if commit:
                conn.commit()
            return ConsumeApprovalResult(
                approval_id=approval_id,
                action_id=action_id,
                action_version=action_version,
                status="CONSUMED",
                noop=True,
            )

        if current_status != "APPROVED":
            raise ApprovalNotConsumable(
                f"approval for action {action_id} v{action_version} "
                f"is {current_status}, not APPROVED"
            )

        cur.execute(
            """
            UPDATE domain.approval
            SET status = 'CONSUMED', consumed_at = now()
            WHERE id = %s AND status = 'APPROVED'
            RETURNING id
            """,
            (str(approval_id),),
        )
        if cur.fetchone() is None:
            raise ApprovalNotConsumable(
                f"approval for action {action_id} v{action_version} could not be consumed"
            )

    if commit:
        conn.commit()
    return ConsumeApprovalResult(
        approval_id=approval_id,
        action_id=action_id,
        action_version=action_version,
        status="CONSUMED",
        noop=False,
    )


def assert_approval_authorizes(
    conn: Connection,
    *,
    action_id: UUID,
    action_version: int,
) -> UUID:
    """Return approval_id if APPROVED/CONSUMED for the exact version (I4).

    Raises ``StaleActionVersion`` when a different version's approval exists
    but the requested version is not authorized. Parent approvals never
    authorize a compensation Action (J9) — binding is exact ``action_id``.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status FROM domain.approval
            WHERE action_id = %s AND action_version = %s
            """,
            (str(action_id), action_version),
        )
        row = cur.fetchone()
        if row is not None and str(row[1]) in {"APPROVED", "CONSUMED"}:
            return UUID(str(row[0]))

        # J9: if this is a compensation, surface parent-approval reuse clearly.
        cur.execute(
            """
            SELECT compensates_action_id, compensates_action_version
            FROM domain.action
            WHERE id = %s
            """,
            (str(action_id),),
        )
        parent_link = cur.fetchone()
        if parent_link is not None and parent_link[0] is not None:
            parent_id = UUID(str(parent_link[0]))
            parent_ver = int(parent_link[1]) if parent_link[1] is not None else None
            cur.execute(
                """
                SELECT id, status, action_version FROM domain.approval
                WHERE action_id = %s AND status IN ('APPROVED', 'CONSUMED')
                ORDER BY action_version DESC
                """,
                (str(parent_id),),
            )
            parent_approvals = cur.fetchall()
            if parent_approvals:
                raise ParentApprovalReuseDenied(
                    "compensation Action requires a fresh Approval; "
                    f"parent {parent_id} v{parent_ver} approval cannot be reused "
                    f"for compensation {action_id} v{action_version}"
                )

        cur.execute(
            """
            SELECT action_version, status FROM domain.approval
            WHERE action_id = %s
            ORDER BY action_version DESC
            """,
            (str(action_id),),
        )
        others = cur.fetchall()
        if others:
            versions = ", ".join(f"v{int(r[0])}={r[1]}" for r in others)
            raise StaleActionVersion(
                f"STALE_ACTION_VERSION: approval does not authorize "
                f"action {action_id} v{action_version} (have {versions})"
            )
        raise StaleActionVersion(
            f"STALE_ACTION_VERSION: no approval for action {action_id} v{action_version}"
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
        cur.execute(
            "SELECT incident_id FROM domain.action WHERE id = %s",
            (str(action_id),),
        )
        action_row = cur.fetchone()
    if action_row is not None and action_row[0] is not None:
        from incidentpilot_shared.timeline import append_timeline_event

        append_timeline_event(
            conn,
            incident_id=UUID(str(action_row[0])),
            event_type="EXECUTION_ATTEMPT_RESERVED",
            summary=(
                f"execution attempt reserved for action {action_id} "
                f"v{action_version} (#{attempt_number})"
            ),
            actor="system",
            payload={
                "attempt_id": str(attempt_id),
                "action_id": str(action_id),
                "action_version": action_version,
                "attempt_number": attempt_number,
            },
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


def append_action_result_evidence_command(
    conn: Connection,
    *,
    incident_id: UUID,
    attempt_id: UUID,
    action_id: UUID,
    action_version: int,
    action_type: str,
    summary: str,
    ok: bool = True,
    adapter_result: dict[str, Any] | None = None,
    error_summary: str | None = None,
    reconciliation_state: str | None = None,
    skipped_execute: bool = False,
    parameters: dict[str, Any] | None = None,
    commit: bool = True,
) -> AppendEvidenceResult:
    """SYSTEM path: RemediationResult → ACTION_RESULT Evidence (J6).

    Called only from remediation-worker after verify/execute. Adapters never
    write Evidence. Fingerprint is attempt-scoped so lost-ACK retries are
    idempotent. Provenance layer is ``ACTION_OBSERVATION``.
    """
    result = append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="ACTION_RESULT",
        fingerprint=f"remediation_worker:attempt:{attempt_id}",
        summary=summary,
        producer="remediation_worker",
        payload={
            "attempt_id": str(attempt_id),
            "action_id": str(action_id),
            "action_version": int(action_version),
            "action_type": action_type,
            "ok": bool(ok),
            "adapter_result": dict(adapter_result or {}),
            "error_summary": error_summary,
            "reconciliation_state": reconciliation_state,
            "skipped_execute": bool(skipped_execute),
            "parameters": dict(parameters or {}),
        },
        provenance={
            "layer": "ACTION_OBSERVATION",
            "writer": "system",
            "source": "remediation_execute",
            "attempt_id": str(attempt_id),
            "action_id": str(action_id),
            "action_version": int(action_version),
            "action_type": action_type,
        },
        commit=False,
    )
    if result.inserted:
        from incidentpilot_shared.audit import append_audit_event
        from incidentpilot_shared.timeline import append_timeline_event

        append_timeline_event(
            conn,
            incident_id=incident_id,
            event_type="REMEDIATION_RESULT",
            summary=summary,
            actor="system",
            payload={
                "attempt_id": str(attempt_id),
                "action_id": str(action_id),
                "action_version": int(action_version),
                "action_type": action_type,
                "ok": bool(ok),
                "evidence_id": str(result.evidence_id),
                "reconciliation_state": reconciliation_state,
            },
        )
        append_audit_event(
            conn,
            incident_id=incident_id,
            action="remediation.execute",
            actor="system",
            resource_type="execution_attempt",
            resource_id=str(attempt_id),
            outcome="success" if ok else "error",
            details={
                "attempt_id": str(attempt_id),
                "action_id": str(action_id),
                "action_version": int(action_version),
                "action_type": action_type,
                "ok": bool(ok),
                "evidence_id": str(result.evidence_id),
                "reconciliation_state": reconciliation_state,
                "skipped_execute": bool(skipped_execute),
                "error_summary": error_summary,
            },
        )
    if commit:
        conn.commit()
    return result


@dataclass(frozen=True, slots=True)
class RecordValidationResultResult:
    validation_result_id: UUID
    incident_id: UUID
    execution_attempt_id: UUID
    outcome: str
    inserted: bool
    incident_state: str | None = None
    incident_revision: int | None = None


def record_validation_result_command(
    conn: Connection,
    *,
    incident_id: UUID,
    execution_attempt_id: UUID,
    outcome: str,
    criteria: dict[str, Any] | None = None,
    observations: dict[str, Any] | None = None,
    action_id: UUID | None = None,
    action_version: int | None = None,
    provenance: dict[str, Any] | None = None,
    transition: bool = True,
    actor: str = "system",
    commit: bool = True,
) -> RecordValidationResultResult:
    """Persist one ValidationResult per execution_attempt (J7).

    Idempotent on ``execution_attempt_id``. Optionally transitions
    ``VALIDATING → RECOVERED|DEGRADED``; canonical post-validation routing
    (RESOLVED / replan / stay DEGRADED) is :func:`route_validation_outcome_command`
    (J8).
    """
    allowed = {
        "RECOVERED",
        "STILL_DEGRADED",
        "UNKNOWN",
        "FAILED_VALIDATION",
    }
    if outcome not in allowed:
        raise ValueError(f"invalid ValidationResult outcome: {outcome!r}")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, outcome FROM domain.validation_result
            WHERE execution_attempt_id = %s
            """,
            (str(execution_attempt_id),),
        )
        existing = cur.fetchone()
        if existing is not None:
            if commit:
                conn.commit()
            return RecordValidationResultResult(
                validation_result_id=UUID(str(existing[0])),
                incident_id=incident_id,
                execution_attempt_id=execution_attempt_id,
                outcome=str(existing[1]),
                inserted=False,
            )

        result_id = uuid4()
        cur.execute(
            """
            INSERT INTO domain.validation_result (
                id, incident_id, execution_attempt_id, action_id, action_version,
                outcome, criteria, observations, provenance
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s::jsonb, %s::jsonb, %s::jsonb
            )
            """,
            (
                str(result_id),
                str(incident_id),
                str(execution_attempt_id),
                str(action_id) if action_id is not None else None,
                action_version,
                outcome,
                json.dumps(criteria or {}),
                json.dumps(observations or {}),
                json.dumps(
                    provenance
                    or {
                        "writer": "system",
                        "source": "validation_window",
                        "layer": "DETERMINISTIC_DERIVED",
                    }
                ),
            ),
        )

    from incidentpilot_shared.timeline import append_timeline_event

    append_timeline_event(
        conn,
        incident_id=incident_id,
        event_type="VALIDATION_RECORDED",
        summary=f"validation outcome {outcome} for attempt {execution_attempt_id}",
        actor=actor,
        payload={
            "validation_result_id": str(result_id),
            "execution_attempt_id": str(execution_attempt_id),
            "outcome": outcome,
            "action_id": str(action_id) if action_id is not None else None,
            "action_version": action_version,
        },
    )

    incident_state: str | None = None
    incident_revision: int | None = None
    if transition:
        to_state: IncidentState | None = None
        if outcome == "RECOVERED":
            to_state = IncidentState.RECOVERED
        elif outcome in {"STILL_DEGRADED", "UNKNOWN", "FAILED_VALIDATION"}:
            to_state = IncidentState.DEGRADED
        if to_state is not None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT state, incident_revision FROM domain.incident
                    WHERE id = %s
                    """,
                    (str(incident_id),),
                )
                row = cur.fetchone()
                if row is None:
                    raise LookupError(f"incident {incident_id} not found")
                current = str(row[0])
                revision = int(row[1])
            if current == IncidentState.VALIDATING.value:
                transitioned = transition_incident_command(
                    conn,
                    incident_id=incident_id,
                    expected_revision=revision,
                    to_state=to_state,
                    actor=actor,
                    commit=False,
                )
                incident_state = (
                    transitioned.to_state.value
                    if hasattr(transitioned.to_state, "value")
                    else str(transitioned.to_state)
                )
                incident_revision = transitioned.new_revision
            else:
                incident_state = current
                incident_revision = revision

    if commit:
        conn.commit()
    return RecordValidationResultResult(
        validation_result_id=result_id,
        incident_id=incident_id,
        execution_attempt_id=execution_attempt_id,
        outcome=outcome,
        inserted=True,
        incident_state=incident_state,
        incident_revision=incident_revision,
    )


# J8 route names (product language). PLANNING_REMEDIATION maps to DIAGNOSED.
ROUTE_RESOLVED = "RESOLVED"
ROUTE_PLANNING_REMEDIATION = "PLANNING_REMEDIATION"
ROUTE_DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class RouteValidationOutcomeResult:
    incident_id: UUID
    execution_attempt_id: UUID
    validation_outcome: str
    route: str
    from_state: str
    to_state: str
    revision: int
    steps: tuple[str, ...]


def _validation_route_for_outcome(outcome: str) -> str:
    """Map ValidationResult outcome → J8 route name.

    Product aliases: PARTIAL/NO_IMPROVEMENT ← STILL_DEGRADED|UNKNOWN;
    REGRESSION ← FAILED_VALIDATION. ``PLANNING_REMEDIATION`` is the route
    name; the incident state used is ``DIAGNOSED`` (Freeze-2).
    """
    if outcome == "RECOVERED":
        return ROUTE_RESOLVED
    if outcome in {"STILL_DEGRADED", "UNKNOWN"}:
        return ROUTE_PLANNING_REMEDIATION
    if outcome == "FAILED_VALIDATION":
        return ROUTE_DEGRADED
    raise ValueError(f"no J8 route for ValidationResult outcome {outcome!r}")


def route_validation_outcome_command(
    conn: Connection,
    *,
    incident_id: UUID,
    execution_attempt_id: UUID,
    actor: str = "system",
    commit: bool = True,
) -> RouteValidationOutcomeResult:
    """Canonical post-validation routing (J8).

    - ``RECOVERED`` → ``RECOVERED`` then ``RESOLVED``
    - ``PARTIAL`` / ``NO_IMPROVEMENT`` / ``STILL_DEGRADED`` / ``UNKNOWN``
      → ``DEGRADED`` then ``DIAGNOSED`` (``PLANNING_REMEDIATION``)
    - ``REGRESSION`` / ``FAILED_VALIDATION`` → ``DEGRADED`` (stay)

    Never takes ``VALIDATING → MITIGATING`` (illegal shortcut).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT outcome FROM domain.validation_result
            WHERE execution_attempt_id = %s
            """,
            (str(execution_attempt_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(
                f"ValidationResult for attempt {execution_attempt_id} not found"
            )
        outcome = str(row[0])
        cur.execute(
            """
            SELECT state, incident_revision FROM domain.incident
            WHERE id = %s
            """,
            (str(incident_id),),
        )
        inc = cur.fetchone()
        if inc is None:
            raise LookupError(f"incident {incident_id} not found")
        current = str(inc[0])
        revision = int(inc[1])

    route = _validation_route_for_outcome(outcome)
    start_state = current
    steps: list[str] = []

    def _advance(to: IncidentState) -> None:
        nonlocal current, revision
        if current == to.value:
            return
        # Defense: never allow the illegal shortcut even if a caller invents it.
        if current == IncidentState.VALIDATING.value and to is IncidentState.MITIGATING:
            raise IllegalTransitionError(
                incident_id=incident_id,
                from_state=IncidentState.VALIDATING,
                to_state=IncidentState.MITIGATING,
            )
        result = transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=revision,
            to_state=to,
            actor=actor,
            commit=False,
        )
        steps.append(f"{current}→{to.value}")
        current = (
            result.to_state.value
            if hasattr(result.to_state, "value")
            else str(result.to_state)
        )
        revision = result.new_revision

    if route == ROUTE_RESOLVED:
        if current == IncidentState.VALIDATING.value:
            _advance(IncidentState.RECOVERED)
        if current == IncidentState.RECOVERED.value:
            _advance(IncidentState.RESOLVED)
    elif route == ROUTE_PLANNING_REMEDIATION:
        if current == IncidentState.VALIDATING.value:
            _advance(IncidentState.DEGRADED)
        if current == IncidentState.DEGRADED.value:
            _advance(IncidentState.DIAGNOSED)
    elif route == ROUTE_DEGRADED:
        if current == IncidentState.VALIDATING.value:
            _advance(IncidentState.DEGRADED)
        # Already DEGRADED / other: stay; do not replan.

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (
                %s, 'VALIDATION_ROUTED', %s, %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                f"validation route {route} from outcome {outcome}",
                actor,
                json.dumps(
                    {
                        "execution_attempt_id": str(execution_attempt_id),
                        "validation_outcome": outcome,
                        "route": route,
                        "from_state": start_state,
                        "to_state": current,
                        "steps": steps,
                    }
                ),
            ),
        )

    if commit:
        conn.commit()
    return RouteValidationOutcomeResult(
        incident_id=incident_id,
        execution_attempt_id=execution_attempt_id,
        validation_outcome=outcome,
        route=route,
        from_state=start_state,
        to_state=current,
        revision=revision,
        steps=tuple(steps),
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
    invocation_id: UUID | None = None,
    commit: bool = True,
) -> RecordAiInvocationResult:
    """Insert ``domain.ai_invocation`` provenance (H2) + optional S3 artifact (L3).

    Required AC fields: model, prompt_version + input evidence ids (in
    ``request_metadata``), status, timestamps (``created_at`` default), incident link.
    L3 sets ``artifact_uri`` when the prompt/tool package was uploaded.
    Pass ``invocation_id`` when the S3 object key must match the row id.
    """
    if status not in _AI_INVOCATION_STATUSES:
        raise ValueError(f"unsupported ai_invocation status: {status!r}")
    meta = dict(request_metadata or {})
    if prompt_version is not None:
        meta.setdefault("prompt_version", prompt_version)
    evidence_tuple: tuple[str, ...] = ()
    if input_evidence_ids is not None:
        evidence_tuple = tuple(str(x) for x in input_evidence_ids)
        meta.setdefault("input_evidence_ids", list(evidence_tuple))
    inv_id = invocation_id or uuid4()
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
                str(inv_id),
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
        artifact_uri=artifact_uri,
        input_evidence_ids=evidence_tuple,
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
    from incidentpilot_shared.timeline import append_timeline_event

    append_timeline_event(
        conn,
        incident_id=incident_id,
        event_type="INCIDENT_CREATED",
        summary=f"incident {public_id} created (DETECTED)",
        actor=actor,
        payload={"public_id": public_id, "title": title, "state": "DETECTED"},
    )
    if commit:
        conn.commit()
    return CreateIncidentResult(incident_id=incident_id, public_id=public_id)


def create_postmortem_draft_command(
    conn: Connection,
    *,
    incident_id: UUID,
    claims: list[dict[str, Any]] | None = None,
    title: str | None = None,
    body_markdown: str | None = None,
    author: str = "system",
    commit: bool = True,
) -> CreatePostmortemDraftResult:
    """Create or refresh a DRAFT postmortem after RESOLVED (L4).

    Claims must cite Evidence / Timeline / Action / ValidationResult on this
    incident. Uncited or unknown citations raise ``UnsupportedClaimError``.
    When ``claims`` is omitted, a deterministic draft is generated from SoR.
    """
    from incidentpilot_shared.postmortem import (
        UnsupportedClaimError,
        build_draft_claims_from_incident,
        claims_to_json,
        parse_claim_dict,
        render_draft_markdown,
        validate_postmortem_claims,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT public_id, title, state
            FROM domain.incident
            WHERE id = %s
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"incident {incident_id} not found")
        public_id, incident_title, state = str(row[0]), str(row[1]), str(row[2])
        if state != IncidentState.RESOLVED.value:
            raise PostmortemNotReadyError(
                f"postmortem draft requires RESOLVED (got {state})"
            )
        cur.execute(
            """
            SELECT id, status FROM domain.postmortem
            WHERE incident_id = %s
            """,
            (str(incident_id),),
        )
        existing = cur.fetchone()
        if existing is not None and str(existing[1]) == "FINAL":
            raise PostmortemFinalImmutableError(
                f"postmortem for {incident_id} is FINAL and immutable"
            )

    if claims is None:
        parsed = build_draft_claims_from_incident(conn, incident_id=incident_id)
        if not parsed:
            raise UnsupportedClaimError(
                "cannot generate draft: no Evidence/Timeline/Action/ValidationResult "
                f"on incident {incident_id}"
            )
    else:
        parsed = [parse_claim_dict(c) for c in claims]

    cited_evidence = validate_postmortem_claims(
        conn, incident_id=incident_id, claims=parsed
    )
    draft_title = (title or f"Postmortem draft — {public_id}").strip()
    body = body_markdown or render_draft_markdown(
        public_id=public_id,
        title=incident_title,
        claims=parsed,
    )
    provenance = {
        "writer": author,
        "source": "postmortem_draft",
        "layer": "DETERMINISTIC_DERIVED",
        "claims": claims_to_json(parsed),
        "quality_rule_id": "postmortem_citations.v1",
    }
    postmortem_id = uuid4()
    inserted = True
    with conn.cursor() as cur:
        if existing is not None:
            postmortem_id = UUID(str(existing[0]))
            inserted = False
            cur.execute(
                """
                UPDATE domain.postmortem
                SET title = %s,
                    body_markdown = %s,
                    cited_evidence_ids = %s::uuid[],
                    author = %s,
                    provenance = %s::jsonb,
                    status = 'DRAFT',
                    updated_at = now()
                WHERE id = %s AND status = 'DRAFT'
                """,
                (
                    draft_title,
                    body,
                    [str(u) for u in cited_evidence],
                    author,
                    json.dumps(provenance),
                    str(postmortem_id),
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO domain.postmortem (
                    id, incident_id, status, title, body_markdown,
                    corrective_actions, cited_evidence_ids, author, provenance
                ) VALUES (
                    %s, %s, 'DRAFT', %s, %s,
                    '[]'::jsonb, %s::uuid[], %s, %s::jsonb
                )
                """,
                (
                    str(postmortem_id),
                    str(incident_id),
                    draft_title,
                    body,
                    [str(u) for u in cited_evidence],
                    author,
                    json.dumps(provenance),
                ),
            )
    if commit:
        conn.commit()
    return CreatePostmortemDraftResult(
        postmortem_id=postmortem_id,
        incident_id=incident_id,
        status="DRAFT",
        title=draft_title,
        claim_count=len(parsed),
        cited_evidence_ids=cited_evidence,
        inserted=inserted,
    )


def _normalize_corrective_actions(
    corrective_actions: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> list[dict[str, Any]]:
    if not corrective_actions:
        raise PostmortemCorrectiveActionsError(
            "FINAL postmortem requires non-empty corrective_actions[]"
        )
    normalized: list[dict[str, Any]] = []
    for i, raw in enumerate(corrective_actions):
        if not isinstance(raw, dict):
            raise PostmortemCorrectiveActionsError(
                f"corrective_actions[{i}] must be an object"
            )
        title = str(raw.get("title") or "").strip()
        if not title:
            raise PostmortemCorrectiveActionsError(
                f"corrective_actions[{i}].title is required"
            )
        item: dict[str, Any] = {"title": title}
        owner = raw.get("owner")
        if owner is not None and str(owner).strip():
            item["owner"] = str(owner).strip()
        for key, value in raw.items():
            if key in {"title", "owner"}:
                continue
            item[key] = value
        normalized.append(item)
    return normalized


def finalize_postmortem_command(
    conn: Connection,
    *,
    incident_id: UUID,
    corrective_actions: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    actor: str = "system",
    commit: bool = True,
) -> FinalizePostmortemResult:
    """DRAFT → FINAL with corrective_actions[]; enter POSTMORTEM if RESOLVED (L5).

    CLOSED remains a separate transition and is gated on FINAL status.
    """
    actions = _normalize_corrective_actions(corrective_actions)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT state, incident_revision FROM domain.incident
            WHERE id = %s
            """,
            (str(incident_id),),
        )
        inc = cur.fetchone()
        if inc is None:
            raise LookupError(f"incident {incident_id} not found")
        state = str(inc[0])
        revision = int(inc[1])
        if state not in {
            IncidentState.RESOLVED.value,
            IncidentState.POSTMORTEM.value,
        }:
            raise PostmortemNotReadyError(
                f"finalize requires RESOLVED or POSTMORTEM (got {state})"
            )
        cur.execute(
            """
            SELECT id, status FROM domain.postmortem
            WHERE incident_id = %s
            """,
            (str(incident_id),),
        )
        pm = cur.fetchone()
        if pm is None:
            raise LookupError(f"postmortem draft not found for incident {incident_id}")
        postmortem_id = UUID(str(pm[0]))
        if str(pm[1]) == "FINAL":
            raise PostmortemFinalImmutableError(
                f"postmortem for {incident_id} is already FINAL"
            )
        if str(pm[1]) != "DRAFT":
            raise PostmortemNotReadyError(f"postmortem status is {pm[1]}, expected DRAFT")
        cur.execute(
            """
            UPDATE domain.postmortem
            SET status = 'FINAL',
                corrective_actions = %s::jsonb,
                author = COALESCE(author, %s),
                provenance = provenance || %s::jsonb
            WHERE id = %s AND status = 'DRAFT'
            """,
            (
                json.dumps(actions),
                actor,
                json.dumps(
                    {
                        "finalized_by": actor,
                        "source": "postmortem_finalize",
                    }
                ),
                str(postmortem_id),
            ),
        )
        if cur.rowcount != 1:
            raise PostmortemFinalImmutableError(
                f"failed to finalize postmortem for {incident_id}"
            )

    incident_state = state
    incident_revision = revision
    if state == IncidentState.RESOLVED.value:
        transitioned = transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=revision,
            to_state=IncidentState.POSTMORTEM,
            actor=actor,
            commit=False,
        )
        incident_state = (
            transitioned.to_state.value
            if hasattr(transitioned.to_state, "value")
            else str(transitioned.to_state)
        )
        incident_revision = transitioned.new_revision

    if commit:
        conn.commit()
    return FinalizePostmortemResult(
        postmortem_id=postmortem_id,
        incident_id=incident_id,
        status="FINAL",
        corrective_actions=tuple(actions),
        incident_state=incident_state,
        incident_revision=incident_revision,
    )


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
            raise ValueError(f"hypothesis {hypothesis_id} not found on incident {incident_id}")
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
    cited = resolve_incident_evidence_refs(conn, incident_id=incident_id, refs=cited_evidence_ids)
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
    cited = resolve_incident_evidence_refs(conn, incident_id=incident_id, refs=cited_evidence_ids)
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
        burn_rate = (
            None if burn_row is None else (float(burn_row[0]) if burn_row[0] is not None else None)
        )
        budget = (
            None if burn_row is None else (float(burn_row[1]) if burn_row[1] is not None else None)
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


def propose_action_command(
    conn: Connection,
    *,
    incident_id: UUID,
    action_type: str,
    parameters: dict[str, Any] | None = None,
    target_ref: dict[str, Any] | None = None,
    action_id: UUID | None = None,
    hypothesis_id: UUID | None = None,
    proposed_by: str = "system",
    rationale: str | None = None,
    commit: bool = True,
) -> ProposeActionResult:
    """Propose a remediation Action bound to the pinned RunbookVersion (I1).

    ``action_type`` must be ∈ pinned ``allowed_action_types``. New parameters on
    an existing action insert an immutable ``action_version`` and bump
    ``current_version``. Adapter execute is out of scope.
    """
    atype = str(action_type).strip()
    if atype not in _KNOWN_ACTION_TYPES:
        raise ValueError(f"invalid action_type: {atype!r}")
    params = dict(parameters or {})
    target = dict(target_ref or {})
    is_rev, reverse_type = _default_reversibility(atype)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pinned_runbook_version_id
            FROM domain.incident
            WHERE id = %s
            """,
            (str(incident_id),),
        )
        inc = cur.fetchone()
        if inc is None:
            raise LookupError(f"incident {incident_id} not found")
        pinned_id = inc[0]
        if pinned_id is None:
            raise PinnedRunbookRequired(
                "ProposeAction requires a pinned RunbookVersion on the incident"
            )
        pinned_uuid = UUID(str(pinned_id))
        cur.execute(
            """
            SELECT allowed_action_types, status
            FROM domain.runbook_version
            WHERE id = %s
            """,
            (str(pinned_uuid),),
        )
        rv = cur.fetchone()
        if rv is None:
            raise ValueError(f"pinned runbook_version not found: {pinned_uuid}")
        if str(rv[1]) != "published":
            raise ValueError("pinned runbook_version must be published")
        allowed = tuple(str(x) for x in (rv[0] or []))
        if atype not in allowed:
            raise ActionTypeNotAllowed(
                f"action_type {atype!r} not in pinned allowed_action_types {list(allowed)}"
            )

    if action_id is not None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT incident_id, action_type, current_version, status,
                       is_reversible, reverse_action_type
                FROM domain.action
                WHERE id = %s
                """,
                (str(action_id),),
            )
            row = cur.fetchone()
            if row is None:
                raise LookupError(f"action {action_id} not found")
            if UUID(str(row[0])) != incident_id:
                raise ValueError("action does not belong to incident")
            if str(row[1]) != atype:
                raise ValueError("cannot change action_type on an existing action")
            current_version = int(row[2])
            status = str(row[3])
            is_rev = bool(row[4])
            reverse_type = str(row[5]) if row[5] is not None else None
            cur.execute(
                """
                SELECT parameters, target_ref
                FROM domain.action_version
                WHERE action_id = %s AND version = %s
                """,
                (str(action_id), current_version),
            )
            ver_row = cur.fetchone()
            assert ver_row is not None
            prev_params = (
                ver_row[0] if isinstance(ver_row[0], dict) else json.loads(ver_row[0] or "{}")
            )
            prev_target = (
                ver_row[1] if isinstance(ver_row[1], dict) else json.loads(ver_row[1] or "{}")
            )
            if prev_params == params and prev_target == target:
                if commit:
                    conn.commit()
                return ProposeActionResult(
                    action_id=action_id,
                    incident_id=incident_id,
                    action_type=atype,
                    version=current_version,
                    current_version=current_version,
                    status=status,
                    parameters=params,
                    runbook_version_id=pinned_uuid,
                    allowed_action_types=allowed,
                    bumped=False,
                    is_reversible=is_rev,
                    reverse_action_type=reverse_type,
                )
            new_version = current_version + 1
            cur.execute(
                """
                INSERT INTO domain.action_version (
                    action_id, version, action_type, parameters, target_ref,
                    is_reversible, reverse_action_type, proposed_by, provenance
                ) VALUES (
                    %s, %s, %s, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s::jsonb
                )
                """,
                (
                    str(action_id),
                    new_version,
                    atype,
                    json.dumps(params),
                    json.dumps(target),
                    is_rev,
                    reverse_type,
                    proposed_by,
                    json.dumps(
                        {
                            "writer": "system",
                            "source": "propose_action",
                            "runbook_version_id": str(pinned_uuid),
                            "rationale": rationale,
                            "bumped_from": current_version,
                        }
                    ),
                ),
            )
            cur.execute(
                """
                UPDATE domain.action
                SET current_version = %s,
                    status = 'PROPOSED',
                    runbook_version_id = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (new_version, str(pinned_uuid), str(action_id)),
            )
            cur.execute(
                """
                INSERT INTO domain.timeline_event (
                    incident_id, event_type, summary, actor, payload
                ) VALUES (
                    %s, 'ACTION_PROPOSED', %s, %s, %s::jsonb
                )
                """,
                (
                    str(incident_id),
                    f"action {action_id} bumped to v{new_version} ({atype})",
                    proposed_by,
                    json.dumps(
                        {
                            "action_id": str(action_id),
                            "version": new_version,
                            "action_type": atype,
                            "bumped": True,
                        }
                    ),
                ),
            )
        if commit:
            conn.commit()
        return ProposeActionResult(
            action_id=action_id,
            incident_id=incident_id,
            action_type=atype,
            version=new_version,
            current_version=new_version,
            status="PROPOSED",
            parameters=params,
            runbook_version_id=pinned_uuid,
            allowed_action_types=allowed,
            bumped=True,
            is_reversible=is_rev,
            reverse_action_type=reverse_type,
        )

    new_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.action (
                id, incident_id, action_type, current_version,
                hypothesis_id, runbook_version_id,
                is_reversible, reverse_action_type, status, proposed_by, provenance
            ) VALUES (
                %s, %s, %s, 1,
                %s, %s,
                %s, %s, 'PROPOSED', %s, %s::jsonb
            )
            """,
            (
                str(new_id),
                str(incident_id),
                atype,
                str(hypothesis_id) if hypothesis_id else None,
                str(pinned_uuid),
                is_rev,
                reverse_type,
                proposed_by,
                json.dumps(
                    {
                        "writer": "system",
                        "source": "propose_action",
                        "runbook_version_id": str(pinned_uuid),
                        "rationale": rationale,
                    }
                ),
            ),
        )
        cur.execute(
            """
            INSERT INTO domain.action_version (
                action_id, version, action_type, parameters, target_ref,
                is_reversible, reverse_action_type, proposed_by, provenance
            ) VALUES (
                %s, 1, %s, %s::jsonb, %s::jsonb,
                %s, %s, %s, %s::jsonb
            )
            """,
            (
                str(new_id),
                atype,
                json.dumps(params),
                json.dumps(target),
                is_rev,
                reverse_type,
                proposed_by,
                json.dumps(
                    {
                        "writer": "system",
                        "source": "propose_action",
                        "runbook_version_id": str(pinned_uuid),
                        "rationale": rationale,
                    }
                ),
            ),
        )
        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (
                %s, 'ACTION_PROPOSED', %s, %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                f"action {new_id} proposed ({atype}) v1",
                proposed_by,
                json.dumps(
                    {
                        "action_id": str(new_id),
                        "version": 1,
                        "action_type": atype,
                        "bumped": False,
                    }
                ),
            ),
        )
    if commit:
        conn.commit()
    return ProposeActionResult(
        action_id=new_id,
        incident_id=incident_id,
        action_type=atype,
        version=1,
        current_version=1,
        status="PROPOSED",
        parameters=params,
        runbook_version_id=pinned_uuid,
        allowed_action_types=allowed,
        bumped=False,
        is_reversible=is_rev,
        reverse_action_type=reverse_type,
    )


def propose_compensation_action_command(
    conn: Connection,
    *,
    parent_action_id: UUID,
    parent_action_version: int | None = None,
    action_type: str | None = None,
    parameters: dict[str, Any] | None = None,
    target_ref: dict[str, Any] | None = None,
    proposed_by: str = "system",
    rationale: str | None = None,
    commit: bool = True,
) -> ProposeActionResult:
    """Propose a new compensation Action linked to a parent (J9).

    Always creates a **new** ``action_id``. Does not copy or inherit the
    parent's PolicyDecision or Approval — EvaluatePolicy + Approval must run
    again for the compensation version.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.incident_id, a.action_type, a.current_version,
                   a.is_reversible, a.reverse_action_type, a.status
            FROM domain.action a
            WHERE a.id = %s
            """,
            (str(parent_action_id),),
        )
        parent = cur.fetchone()
        if parent is None:
            raise LookupError(f"parent action {parent_action_id} not found")
        incident_id = UUID(str(parent[0]))
        parent_type = str(parent[1])
        current_version = int(parent[2])
        parent_version = (
            int(parent_action_version)
            if parent_action_version is not None
            else current_version
        )
        reverse_type = str(parent[4]) if parent[4] is not None else None
        cur.execute(
            """
            SELECT 1 FROM domain.action_version
            WHERE action_id = %s AND version = %s
            """,
            (str(parent_action_id), parent_version),
        )
        if cur.fetchone() is None:
            raise CompensationParentRequired(
                f"parent action_version {parent_action_id} v{parent_version} not found"
            )

    atype = (action_type or reverse_type or "").strip()
    if not atype:
        raise CompensationActionTypeRequired(
            f"parent {parent_action_id} ({parent_type}) has no reverse_action_type; "
            "pass action_type explicitly"
        )

    # Propose as a brand-new action, then stamp the compensation link.
    proposed = propose_action_command(
        conn,
        incident_id=incident_id,
        action_type=atype,
        parameters=parameters,
        target_ref=target_ref,
        action_id=None,
        proposed_by=proposed_by,
        rationale=rationale
        or f"compensation for {parent_action_id} v{parent_version}",
        commit=False,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE domain.action
            SET compensates_action_id = %s,
                compensates_action_version = %s,
                provenance = provenance || %s::jsonb,
                updated_at = now()
            WHERE id = %s
            """,
            (
                str(parent_action_id),
                parent_version,
                json.dumps(
                    {
                        "compensation": True,
                        "compensates_action_id": str(parent_action_id),
                        "compensates_action_version": parent_version,
                        "parent_action_type": parent_type,
                        "inherits_parent_approval": False,
                    }
                ),
                str(proposed.action_id),
            ),
        )
        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (
                %s, 'COMPENSATION_PROPOSED', %s, %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                f"compensation {proposed.action_id} for parent {parent_action_id} "
                f"v{parent_version}",
                proposed_by,
                json.dumps(
                    {
                        "action_id": str(proposed.action_id),
                        "version": proposed.version,
                        "action_type": proposed.action_type,
                        "compensates_action_id": str(parent_action_id),
                        "compensates_action_version": parent_version,
                        "inherits_parent_approval": False,
                    }
                ),
            ),
        )

    if commit:
        conn.commit()
    return ProposeActionResult(
        action_id=proposed.action_id,
        incident_id=proposed.incident_id,
        action_type=proposed.action_type,
        version=proposed.version,
        current_version=proposed.current_version,
        status=proposed.status,
        parameters=proposed.parameters,
        runbook_version_id=proposed.runbook_version_id,
        allowed_action_types=proposed.allowed_action_types,
        bumped=False,
        is_reversible=proposed.is_reversible,
        reverse_action_type=proposed.reverse_action_type,
        compensates_action_id=parent_action_id,
        compensates_action_version=parent_version,
    )


def load_active_policy_definition(
    conn: Connection,
    *,
    policy_key: str = "default",
) -> PolicyDefinitionResult:
    """Load the active policy_definition for EvaluatePolicy (I7)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.policy_key, d.version, d.version_label, d.body,
                   d.notes, d.created_by
            FROM domain.policy_active a
            JOIN domain.policy_definition d
              ON d.policy_key = a.policy_key AND d.version = a.version
            WHERE a.policy_key = %s
            """,
            (policy_key,),
        )
        row = cur.fetchone()
        if row is None:
            # Fallback before migration / empty DB — match I2 defaults.
            return PolicyDefinitionResult(
                policy_definition_id=uuid4(),
                policy_key=policy_key,
                version=1,
                version_label="v1",
                body={},
                notes=None,
                created_by="system",
                active=True,
            )
        body = row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}")
        return PolicyDefinitionResult(
            policy_definition_id=UUID(str(row[0])),
            policy_key=str(row[1]),
            version=int(row[2]),
            version_label=str(row[3]),
            body=body,
            notes=None if row[5] is None else str(row[5]),
            created_by=str(row[6]),
            active=True,
        )


def list_policy_definitions(
    conn: Connection,
    *,
    policy_key: str = "default",
) -> list[PolicyDefinitionResult]:
    """History of policy versions for a key (I7)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.policy_key, d.version, d.version_label, d.body,
                   d.notes, d.created_by,
                   (a.version IS NOT NULL) AS is_active
            FROM domain.policy_definition d
            LEFT JOIN domain.policy_active a
              ON a.policy_key = d.policy_key AND a.version = d.version
            WHERE d.policy_key = %s
            ORDER BY d.version DESC
            """,
            (policy_key,),
        )
        rows = cur.fetchall()
    out: list[PolicyDefinitionResult] = []
    for row in rows:
        body = row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}")
        out.append(
            PolicyDefinitionResult(
                policy_definition_id=UUID(str(row[0])),
                policy_key=str(row[1]),
                version=int(row[2]),
                version_label=str(row[3]),
                body=body,
                notes=None if row[5] is None else str(row[5]),
                created_by=str(row[6]),
                active=bool(row[7]),
            )
        )
    return out


def publish_policy_version_command(
    conn: Connection,
    *,
    policy_key: str = "default",
    body: dict[str, Any] | None = None,
    notes: str | None = None,
    created_by: str = "admin",
    activate: bool = True,
    commit: bool = True,
) -> PolicyDefinitionResult:
    """Append a new immutable policy version (I7). Never rewrites past rows."""
    key = (policy_key or "default").strip() or "default"
    payload = dict(body or {})
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(version), 0) FROM domain.policy_definition
            WHERE policy_key = %s
            """,
            (key,),
        )
        next_version = int(cur.fetchone()[0]) + 1
        version_label = f"v{next_version}"
        definition_id = uuid4()
        cur.execute(
            """
            INSERT INTO domain.policy_definition (
                id, policy_key, version, version_label, body, notes, created_by
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                str(definition_id),
                key,
                next_version,
                version_label,
                json.dumps(payload),
                notes,
                created_by,
            ),
        )
        cur.execute(
            """
            INSERT INTO domain.audit_event (
                incident_id, action, actor, resource_type, resource_id, details
            ) VALUES (
                NULL, 'policy.publish', %s, 'policy_definition', %s, %s::jsonb
            )
            """,
            (
                created_by,
                str(definition_id),
                json.dumps(
                    {
                        "policy_key": key,
                        "version": next_version,
                        "version_label": version_label,
                        "activate": activate,
                        "notes": notes,
                    }
                ),
            ),
        )
    if activate:
        activate_policy_version_command(
            conn,
            policy_key=key,
            version=next_version,
            activated_by=created_by,
            commit=False,
        )
    if commit:
        conn.commit()
    return PolicyDefinitionResult(
        policy_definition_id=definition_id,
        policy_key=key,
        version=next_version,
        version_label=version_label,
        body=payload,
        notes=notes,
        created_by=created_by,
        active=activate,
    )


def activate_policy_version_command(
    conn: Connection,
    *,
    policy_key: str,
    version: int,
    activated_by: str = "admin",
    commit: bool = True,
) -> ActivatePolicyResult:
    """Point policy_active at an existing immutable version (I7)."""
    key = (policy_key or "default").strip() or "default"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT version_label FROM domain.policy_definition
            WHERE policy_key = %s AND version = %s
            """,
            (key, int(version)),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"policy {key} version {version} not found")
        version_label = str(row[0])
        cur.execute(
            """
            INSERT INTO domain.policy_active (
                policy_key, version, activated_at, activated_by
            ) VALUES (%s, %s, now(), %s)
            ON CONFLICT (policy_key) DO UPDATE
            SET version = EXCLUDED.version,
                activated_at = now(),
                activated_by = EXCLUDED.activated_by
            """,
            (key, int(version), activated_by),
        )
        cur.execute(
            """
            INSERT INTO domain.audit_event (
                incident_id, action, actor, resource_type, resource_id, details
            ) VALUES (
                NULL, 'policy.activate', %s, 'policy_active', %s, %s::jsonb
            )
            """,
            (
                activated_by,
                key,
                json.dumps(
                    {
                        "policy_key": key,
                        "version": int(version),
                        "version_label": version_label,
                    }
                ),
            ),
        )
    if commit:
        conn.commit()
    return ActivatePolicyResult(
        policy_key=key,
        version=int(version),
        version_label=version_label,
        activated_by=activated_by,
    )


def upsert_autonomy_config_command(
    conn: Connection,
    *,
    autonomy_level: int,
    service_key: str | None = None,
    action_type: str | None = None,
    environment: str | None = None,
    severity: str | None = None,
    notes: str | None = None,
    actor: str = "admin",
    commit: bool = True,
) -> UpsertAutonomyConfigResult:
    """Insert or update an autonomy config row (I3). NULL dims = wildcards."""
    level = int(autonomy_level)
    if level not in {1, 2, 3}:
        raise ValueError("autonomy_level must be 1, 2, or 3")
    svc = (service_key or "").strip() or None
    atype = (action_type or "").strip() or None
    env = (environment or "").strip() or None
    sev = (severity or "").strip() or None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM domain.autonomy_config
            WHERE COALESCE(service_key, '') = COALESCE(%s, '')
              AND COALESCE(action_type, '') = COALESCE(%s, '')
              AND COALESCE(environment, '') = COALESCE(%s, '')
              AND COALESCE(severity, '') = COALESCE(%s, '')
            LIMIT 1
            """,
            (svc, atype, env, sev),
        )
        existing = cur.fetchone()
        if existing is not None:
            returned_id = UUID(str(existing[0]))
            cur.execute(
                """
                UPDATE domain.autonomy_config
                SET autonomy_level = %s,
                    notes = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (level, notes, str(returned_id)),
            )
            inserted = False
        else:
            returned_id = uuid4()
            cur.execute(
                """
                INSERT INTO domain.autonomy_config (
                    id, service_key, action_type, environment, severity,
                    autonomy_level, notes
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (str(returned_id), svc, atype, env, sev, level, notes),
            )
            inserted = True
    from incidentpilot_shared.audit import append_audit_event

    append_audit_event(
        conn,
        action="admin.autonomy_upsert",
        actor=actor,
        resource_type="autonomy_config",
        resource_id=str(returned_id),
        outcome="success",
        details={
            "config_id": str(returned_id),
            "service_key": svc,
            "action_type": atype,
            "environment": env,
            "severity": sev,
            "autonomy_level": level,
            "inserted": inserted,
            "notes": notes,
        },
    )
    if commit:
        conn.commit()
    return UpsertAutonomyConfigResult(
        config_id=returned_id,
        service_key=svc,
        action_type=atype,
        environment=env,
        severity=sev,
        autonomy_level=level,
        notes=notes,
        inserted=inserted,
    )


def evaluate_policy_command(
    conn: Connection,
    *,
    action_id: UUID,
    action_version: int | None = None,
    autonomy_level: int | None = None,
    actor: str = "system",
    commit: bool = True,
) -> EvaluatePolicyResult:
    """SYSTEM EvaluatePolicy → immutable PolicyDecision (I2/I3).

    When ``autonomy_level`` is omitted, resolve from ``domain.autonomy_config``
    (I3). AI sandbox cannot invoke this. BLOCK is absolute.
    """
    if actor not in _POLICY_ACTORS or actor.startswith("ai_"):
        raise PolicyActorDenied(f"actor {actor!r} cannot EvaluatePolicy (SYSTEM only)")

    from incidentpilot_shared.autonomy import resolve_autonomy_level
    from incidentpilot_shared.processors.policy import evaluate_policy

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.incident_id, a.action_type, a.current_version, a.status,
                   i.severity
            FROM domain.action a
            JOIN domain.incident i ON i.id = a.incident_id
            WHERE a.id = %s
            """,
            (str(action_id),),
        )
        action_row = cur.fetchone()
        if action_row is None:
            raise LookupError(f"action {action_id} not found")
        incident_id = UUID(str(action_row[0]))
        action_type = str(action_row[1])
        current_version = int(action_row[2])
        version = int(action_version) if action_version is not None else current_version
        incident_severity = str(action_row[4]) if action_row[4] is not None else None

        cur.execute(
            """
            SELECT parameters
            FROM domain.action_version
            WHERE action_id = %s AND version = %s
            """,
            (str(action_id), version),
        )
        ver = cur.fetchone()
        if ver is None:
            raise LookupError(f"action_version {action_id} v{version} not found")
        parameters = ver[0] if isinstance(ver[0], dict) else json.loads(ver[0] or "{}")

        cur.execute(
            """
            SELECT s.key, s.environment
            FROM domain.incident_service isv
            JOIN domain.service s ON s.id = isv.service_id
            WHERE isv.incident_id = %s
            ORDER BY isv.created_at ASC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        svc_row = cur.fetchone()
        service_key = str(svc_row[0]) if svc_row is not None else None
        environment = str(svc_row[1]) if svc_row is not None else "local"

        cur.execute(
            """
            SELECT id FROM domain.policy_decision
            WHERE action_id = %s AND action_version = %s
            """,
            (str(action_id), version),
        )
        if cur.fetchone() is not None:
            raise PolicyDecisionExists(
                f"PolicyDecision already exists for action {action_id} v{version}"
            )

    if autonomy_level is None:
        match = resolve_autonomy_level(
            conn,
            service_key=service_key,
            action_type=action_type,
            environment=environment,
            severity=incident_severity,
        )
        resolved_level = match.autonomy_level
        autonomy_source = match.source
        autonomy_meta = {
            "config_id": match.config_id,
            "specificity": match.specificity,
            "notes": match.notes,
            "matched": {
                "service_key": match.service_key,
                "action_type": match.action_type,
                "environment": match.environment,
                "severity": match.severity,
            },
        }
    else:
        resolved_level = int(autonomy_level)
        autonomy_source = "explicit"
        autonomy_meta = {"config_id": None}

    active = load_active_policy_definition(conn, policy_key="default")
    verdict = evaluate_policy(
        action_type=action_type,
        parameters=parameters,
        autonomy_level=resolved_level,
        policy_key=active.policy_key,
        policy_version=active.version_label,
        policy_body=active.body,
    )
    decision_id = uuid4()
    if verdict.decision == "BLOCK":
        new_status = "BLOCKED"
    elif verdict.decision == "REQUIRE_APPROVAL":
        new_status = "AWAITING_APPROVAL"
    else:
        new_status = "POLICY_EVALUATED"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.policy_decision (
                id, action_id, action_version, decision, reason,
                policy_key, policy_version, provenance
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb
            )
            """,
            (
                str(decision_id),
                str(action_id),
                version,
                verdict.decision,
                verdict.reason,
                verdict.policy_key,
                verdict.policy_version,
                json.dumps(
                    {
                        "writer": "system",
                        "source": "evaluate_policy",
                        "quality_rule_id": verdict.quality_rule_id,
                        "actor": actor,
                        "inputs": verdict.inputs,
                        "autonomy_level": resolved_level,
                        "autonomy_source": autonomy_source,
                        "autonomy": autonomy_meta,
                        "context": {
                            "service_key": service_key,
                            "environment": environment,
                            "severity": incident_severity,
                        },
                    }
                ),
            ),
        )
        cur.execute(
            """
            UPDATE domain.action
            SET status = %s, updated_at = now()
            WHERE id = %s
            """,
            (new_status, str(action_id)),
        )
        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (
                %s, 'POLICY_DECISION', %s, %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                f"policy {verdict.decision} for action {action_id} v{version}",
                actor,
                json.dumps(
                    {
                        "action_id": str(action_id),
                        "action_version": version,
                        "decision": verdict.decision,
                        "reason": verdict.reason,
                        "policy_decision_id": str(decision_id),
                    }
                ),
            ),
        )
        cur.execute(
            """
            INSERT INTO domain.audit_event (
                incident_id, action, actor, resource_type, resource_id, details
            ) VALUES (
                %s, 'policy.evaluate', %s, 'policy_decision', %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                actor,
                str(decision_id),
                json.dumps(
                    {
                        "action_id": str(action_id),
                        "action_version": version,
                        "decision": verdict.decision,
                        "reason": verdict.reason,
                    }
                ),
            ),
        )
    if verdict.decision == "REQUIRE_APPROVAL":
        # I4: PENDING approval bound to this exact version (idempotent).
        create_approval_command(
            conn,
            action_id=action_id,
            action_version=version,
            commit=False,
        )
    if commit:
        conn.commit()
    return EvaluatePolicyResult(
        policy_decision_id=decision_id,
        action_id=action_id,
        action_version=version,
        incident_id=incident_id,
        decision=verdict.decision,
        reason=verdict.reason,
        policy_key=verdict.policy_key,
        policy_version=verdict.policy_version,
        action_status=new_status,
        autonomy_level=resolved_level,
        autonomy_source=autonomy_source,
    )


def confirm_hypothesis_command(
    conn: Connection,
    *,
    incident_id: UUID,
    hypothesis_id: UUID,
    actor: str = "system",
    commit: bool = True,
) -> ConfirmHypothesisResult:
    """SYSTEM confirmation rules → Hypothesis CONFIRMED (+ optional CAUSED_BY).

    Wired after ValidationResult RECOVERED (J8/H10). RECOVERED alone never
    confirms. AI / humans cannot CONFIRM or write CAUSED_BY directly.
    """
    if actor not in _CONFIRM_ACTORS or actor.startswith("ai_"):
        raise ConfirmActorDenied(f"actor {actor!r} cannot CONFIRM hypothesis (SYSTEM rules only)")

    from incidentpilot_shared.processors.confirmation import (
        ConfirmationSignals,
        evaluate_confirmation_rules,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, hypothesis_class, cited_evidence_ids
            FROM domain.hypothesis
            WHERE id = %s AND incident_id = %s
            """,
            (str(hypothesis_id), str(incident_id)),
        )
        hypo = cur.fetchone()
        if hypo is None:
            raise LookupError(f"hypothesis {hypothesis_id} not found on incident {incident_id}")
        status = str(hypo[0])
        hypo_class = str(hypo[1]) if hypo[1] is not None else None
        cited = list(hypo[2] or [])

        cur.execute(
            """
            SELECT 1
            FROM domain.validation_result
            WHERE incident_id = %s AND outcome = 'RECOVERED'
            ORDER BY decided_at DESC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        recovered = cur.fetchone() is not None

        cur.execute(
            """
            SELECT kind, id
            FROM domain.evidence
            WHERE incident_id = %s AND kind IN ('CHANGE', 'ACTION_RESULT', 'METRIC')
            """,
            (str(incident_id),),
        )
        kind_rows = cur.fetchall()
        has_change = any(str(r[0]) == "CHANGE" for r in kind_rows)
        has_action = any(str(r[0]) == "ACTION_RESULT" for r in kind_rows)
        change_ids = [UUID(str(r[1])) for r in kind_rows if str(r[0]) == "CHANGE"]
        metric_ids = [UUID(str(r[1])) for r in kind_rows if str(r[0]) == "METRIC"]

    decision = evaluate_confirmation_rules(
        ConfirmationSignals(
            hypothesis_status=status,
            hypothesis_class=hypo_class,
            validation_recovered=recovered,
            has_change_evidence=has_change,
            has_action_result_evidence=has_action,
            cited_evidence_count=len(cited),
        )
    )
    if not decision.confirm:
        raise ConfirmationRulesNotMet(decision.reason)

    caused_by_written = False
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE domain.hypothesis
            SET status = 'CONFIRMED',
                updated_at = now(),
                provenance = provenance || %s::jsonb
            WHERE id = %s AND incident_id = %s
            """,
            (
                json.dumps(
                    {
                        "writer": "system",
                        "source": "hypothesis_confirm",
                        "quality_rule_id": decision.quality_rule_id,
                        "reason": decision.reason,
                        "inputs": decision.inputs,
                    }
                ),
                str(hypothesis_id),
                str(incident_id),
            ),
        )
        if decision.write_caused_by and change_ids:
            target = change_ids[0]
            source: UUID | None = next(
                (m for m in metric_ids if m != target),
                None,
            )
            if source is None:
                for raw in cited:
                    candidate = UUID(str(raw))
                    if candidate != target:
                        source = candidate
                        break
            if source is not None:
                # Symptom CAUSED_BY CHANGE (deploy) — SYSTEM confirmation only.
                link_evidence_relation_command(
                    conn,
                    from_evidence_id=source,
                    to_evidence_id=target,
                    relation_type="CAUSED_BY",
                    commit=False,
                    via_confirmation_gate=True,
                )
                caused_by_written = True

        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (
                %s, 'HYPOTHESIS_CONFIRMED', %s, %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                f"hypothesis {hypothesis_id} CONFIRMED ({hypo_class or 'unclassified'})",
                actor,
                json.dumps(
                    {
                        "hypothesis_id": str(hypothesis_id),
                        "hypothesis_class": hypo_class,
                        "caused_by_written": caused_by_written,
                        "reason": decision.reason,
                        "quality_rule_id": decision.quality_rule_id,
                    }
                ),
            ),
        )
        cur.execute(
            """
            INSERT INTO domain.audit_event (
                incident_id, action, actor, resource_type, resource_id, details
            ) VALUES (
                %s, 'hypothesis.confirm', %s, 'hypothesis', %s, %s::jsonb
            )
            """,
            (
                str(incident_id),
                actor,
                str(hypothesis_id),
                json.dumps(
                    {
                        "caused_by_written": caused_by_written,
                        "reason": decision.reason,
                        "quality_rule_id": decision.quality_rule_id,
                    }
                ),
            ),
        )
    if commit:
        conn.commit()
    return ConfirmHypothesisResult(
        incident_id=incident_id,
        hypothesis_id=hypothesis_id,
        status="CONFIRMED",
        hypothesis_class=hypo_class,
        caused_by_written=caused_by_written,
        reason=decision.reason,
        quality_rule_id=decision.quality_rule_id,
        inputs=decision.inputs,
    )
