"""Read endpoints for alerts, evidence, hypotheses, actions, approvals, timeline, postmortem."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from psycopg.rows import dict_row

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.commands import (
    ConfirmActorDenied,
    ConfirmationRulesNotMet,
    SeverityActorDenied,
    compute_impact_snapshot_command,
    compute_slo_burn_command,
    confirm_hypothesis_command,
    update_incident_severity_command,
)
from incidentpilot_api.db import get_conn
from incidentpilot_api.rbac import Permission, require_permission
from incidentpilot_api.schemas import (
    ActionOut,
    AlertOut,
    ApprovalOut,
    EvidenceOut,
    HypothesisConfirmOut,
    HypothesisOut,
    ImpactSnapshotOut,
    PostmortemOut,
    SeverityUpdateOut,
    SloBurnOut,
    TimelineEventOut,
)

router = APIRouter(tags=["resources"])


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
    incident_id: UUID | None = None,
) -> list[AlertOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    sql = """
        SELECT id, fingerprint, source, status, incident_id, received_at
        FROM domain.alert
    """
    params: list[object] = []
    if incident_id is not None:
        sql += " WHERE incident_id = %s"
        params.append(str(incident_id))
    sql += " ORDER BY received_at DESC LIMIT 100"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [AlertOut(**row) for row in cur.fetchall()]


@router.get("/evidence", response_model=list[EvidenceOut])
def list_evidence(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
    incident_id: UUID | None = None,
) -> list[EvidenceOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    sql = """
        SELECT id, evidence_key, incident_id, kind, summary, fingerprint,
               observed_at, producer
        FROM domain.evidence
    """
    params: list[object] = []
    if incident_id is not None:
        sql += " WHERE incident_id = %s"
        params.append(str(incident_id))
    sql += " ORDER BY observed_at DESC LIMIT 100"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [EvidenceOut(**row) for row in cur.fetchall()]


@router.get("/hypotheses", response_model=list[HypothesisOut])
def list_hypotheses(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
    incident_id: UUID | None = None,
) -> list[HypothesisOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    sql = """
        SELECT id, incident_id, status, statement, proposed_by, confidence, rank,
               COALESCE(provenance->>'score_kind', 'heuristic') AS score_kind
        FROM domain.hypothesis
    """
    params: list[object] = []
    if incident_id is not None:
        sql += " WHERE incident_id = %s"
        params.append(str(incident_id))
    sql += " ORDER BY rank NULLS LAST, created_at DESC LIMIT 100"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [HypothesisOut(**row) for row in cur.fetchall()]


@router.get("/actions", response_model=list[ActionOut])
def list_actions(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
    incident_id: UUID | None = None,
) -> list[ActionOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    sql = """
        SELECT id, incident_id, action_type, status, current_version, is_reversible
        FROM domain.action
    """
    params: list[object] = []
    if incident_id is not None:
        sql += " WHERE incident_id = %s"
        params.append(str(incident_id))
    sql += " ORDER BY created_at DESC LIMIT 100"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [ActionOut(**row) for row in cur.fetchall()]


@router.get("/approvals", response_model=list[ApprovalOut])
def list_approvals(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> list[ApprovalOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, action_id, action_version, status, decided_by
            FROM domain.approval
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
        return [ApprovalOut(**row) for row in cur.fetchall()]


@router.get("/incidents/{incident_id}/timeline", response_model=list[TimelineEventOut])
def list_timeline(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> list[TimelineEventOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, incident_id, event_type, summary, actor, occurred_at, payload
            FROM domain.timeline_event
            WHERE incident_id = %s
            ORDER BY occurred_at DESC
            LIMIT 200
            """,
            (str(incident_id),),
        )
        return [TimelineEventOut(**row) for row in cur.fetchall()]


@router.get(
    "/incidents/{incident_id}/impact-snapshots",
    response_model=list[ImpactSnapshotOut],
)
def list_impact_snapshots(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> list[ImpactSnapshotOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, incident_id, captured_at, severity, customer_impact_summary,
                   estimated_affected_users, metrics, provenance
            FROM domain.impact_snapshot
            WHERE incident_id = %s
            ORDER BY captured_at DESC
            LIMIT 100
            """,
            (str(incident_id),),
        )
        return [ImpactSnapshotOut(**row) for row in cur.fetchall()]


@router.post(
    "/incidents/{incident_id}/impact-snapshots/compute",
    response_model=ImpactSnapshotOut,
)
def compute_impact_snapshot(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> ImpactSnapshotOut:
    require_permission(principal, Permission.INCIDENT_WRITE)
    try:
        result = compute_impact_snapshot_command(conn, incident_id=incident_id, commit=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, incident_id, captured_at, severity, customer_impact_summary,
                   estimated_affected_users, metrics, provenance
            FROM domain.impact_snapshot
            WHERE id = %s
            """,
            (str(result.snapshot_id),),
        )
        row = cur.fetchone()
    assert row is not None
    return ImpactSnapshotOut(**row)


@router.get("/incidents/{incident_id}/slo-burns", response_model=list[SloBurnOut])
def list_slo_burns(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> list[SloBurnOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, incident_id, slo_key, window_label, burn_rate,
                   error_budget_remaining, observed_at, payload, provenance
            FROM domain.slo_burn
            WHERE incident_id = %s
            ORDER BY observed_at DESC
            LIMIT 100
            """,
            (str(incident_id),),
        )
        return [SloBurnOut(**row) for row in cur.fetchall()]


@router.post("/incidents/{incident_id}/slo-burns/compute", response_model=SloBurnOut)
def compute_slo_burn(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> SloBurnOut:
    require_permission(principal, Permission.INCIDENT_WRITE)
    try:
        result = compute_slo_burn_command(conn, incident_id=incident_id, commit=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, incident_id, slo_key, window_label, burn_rate,
                   error_budget_remaining, observed_at, payload, provenance
            FROM domain.slo_burn
            WHERE id = %s
            """,
            (str(result.slo_burn_id),),
        )
        row = cur.fetchone()
    assert row is not None
    return SloBurnOut(**row)


@router.post(
    "/incidents/{incident_id}/hypotheses/{hypothesis_id}/confirm",
    response_model=HypothesisConfirmOut,
)
def confirm_hypothesis(
    incident_id: UUID,
    hypothesis_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> HypothesisConfirmOut:
    """SYSTEM confirmation rules after ValidationResult RECOVERED (H10)."""
    require_permission(principal, Permission.INCIDENT_WRITE)
    try:
        result = confirm_hypothesis_command(
            conn,
            incident_id=incident_id,
            hypothesis_id=hypothesis_id,
            actor="system",
            commit=True,
        )
    except ConfirmActorDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConfirmationRulesNotMet as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return HypothesisConfirmOut(
        incident_id=result.incident_id,
        hypothesis_id=result.hypothesis_id,
        status=result.status,
        hypothesis_class=result.hypothesis_class,
        caused_by_written=result.caused_by_written,
        reason=result.reason,
        quality_rule_id=result.quality_rule_id,
        inputs=result.inputs,
    )


@router.post(
    "/incidents/{incident_id}/severity/update",
    response_model=SeverityUpdateOut,
)
def update_incident_severity(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> SeverityUpdateOut:
    """SYSTEM rules recompute incident.severity (H8). HTTP callers trigger SYSTEM."""
    require_permission(principal, Permission.INCIDENT_WRITE)
    try:
        result = update_incident_severity_command(
            conn,
            incident_id=incident_id,
            actor="system",
            commit=True,
        )
    except SeverityActorDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SeverityUpdateOut(
        incident_id=result.incident_id,
        previous_severity=result.previous_severity,
        severity=result.severity,
        changed=result.changed,
        explanation=result.explanation,
        quality_rule_id=result.quality_rule_id,
        inputs=result.inputs,
    )


@router.get("/incidents/{incident_id}/postmortem", response_model=PostmortemOut)
def get_postmortem(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> PostmortemOut:
    require_permission(principal, Permission.INCIDENT_READ)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, incident_id, status, title, body_markdown, corrective_actions
            FROM domain.postmortem
            WHERE incident_id = %s
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="postmortem not found")
    return PostmortemOut(**row)
