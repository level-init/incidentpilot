"""Read endpoints for alerts, evidence, hypotheses, actions, approvals, timeline, postmortem."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection
from psycopg.rows import dict_row

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.commands import (
    ActionTypeNotAllowed,
    ConfirmActorDenied,
    ConfirmationRulesNotMet,
    PinnedRunbookRequired,
    PolicyActorDenied,
    PolicyDecisionExists,
    PostmortemCorrectiveActionsError,
    PostmortemFinalImmutableError,
    PostmortemNotReadyError,
    SeverityActorDenied,
    activate_policy_version_command,
    compute_impact_snapshot_command,
    compute_slo_burn_command,
    confirm_hypothesis_command,
    create_postmortem_draft_command,
    evaluate_policy_command,
    export_postmortem_package_command,
    finalize_postmortem_command,
    list_policy_definitions,
    propose_action_command,
    publish_policy_version_command,
    update_incident_severity_command,
    upsert_autonomy_config_command,
)
from incidentpilot_api.db import get_conn
from incidentpilot_api.rbac import Permission, require_permission
from incidentpilot_api.schemas import (
    ActionOut,
    ActionPropose,
    ActionProposeOut,
    AlertOut,
    ApprovalOut,
    AuditEventOut,
    AutonomyConfigOut,
    AutonomyConfigUpsert,
    EvidenceOut,
    HypothesisConfirmOut,
    HypothesisOut,
    ImpactSnapshotOut,
    PolicyActivateOut,
    PolicyDecisionOut,
    PolicyEvaluateBody,
    PolicyVersionOut,
    PolicyVersionPublish,
    PostmortemDraftCreate,
    PostmortemDraftOut,
    PostmortemExportOut,
    PostmortemFinalize,
    PostmortemFinalizeOut,
    PostmortemOut,
    SeverityUpdateOut,
    SloBurnOut,
    TimelineEventOut,
)
from incidentpilot_shared.postmortem import UnsupportedClaimError

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


@router.post(
    "/incidents/{incident_id}/actions",
    response_model=ActionProposeOut,
    status_code=201,
)
def propose_action(
    incident_id: UUID,
    body: ActionPropose,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> ActionProposeOut:
    """ProposeAction bound to pinned runbook allowlist (I1)."""
    require_permission(principal, Permission.INCIDENT_WRITE)
    try:
        result = propose_action_command(
            conn,
            incident_id=incident_id,
            action_type=body.action_type,
            parameters=body.parameters,
            target_ref=body.target_ref,
            action_id=body.action_id,
            hypothesis_id=body.hypothesis_id,
            proposed_by=principal.actor_id,
            rationale=body.rationale,
            commit=True,
        )
    except PinnedRunbookRequired as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ActionTypeNotAllowed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionProposeOut(
        action_id=result.action_id,
        incident_id=result.incident_id,
        action_type=result.action_type,
        version=result.version,
        current_version=result.current_version,
        status=result.status,
        parameters=result.parameters,
        runbook_version_id=result.runbook_version_id,
        allowed_action_types=list(result.allowed_action_types),
        bumped=result.bumped,
        is_reversible=result.is_reversible,
        reverse_action_type=result.reverse_action_type,
    )


@router.post(
    "/actions/{action_id}/policy/evaluate",
    response_model=PolicyDecisionOut,
)
def evaluate_action_policy(
    action_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
    body: PolicyEvaluateBody | None = None,
) -> PolicyDecisionOut:
    """SYSTEM EvaluatePolicy (I2). HTTP triggers SYSTEM — AI cannot POLICY_EVAL."""
    require_permission(principal, Permission.INCIDENT_WRITE)
    payload = body or PolicyEvaluateBody()
    try:
        result = evaluate_policy_command(
            conn,
            action_id=action_id,
            action_version=payload.action_version,
            autonomy_level=payload.autonomy_level,
            actor="system",
            commit=True,
        )
    except PolicyActorDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PolicyDecisionExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PolicyDecisionOut(
        policy_decision_id=result.policy_decision_id,
        action_id=result.action_id,
        action_version=result.action_version,
        incident_id=result.incident_id,
        decision=result.decision,
        reason=result.reason,
        policy_key=result.policy_key,
        policy_version=result.policy_version,
        action_status=result.action_status,
        autonomy_level=result.autonomy_level,
        autonomy_source=result.autonomy_source,
    )


@router.get("/autonomy-config", response_model=list[AutonomyConfigOut])
def list_autonomy_config(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> list[AutonomyConfigOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id AS config_id, service_key, action_type, environment,
                   severity, autonomy_level, notes
            FROM domain.autonomy_config
            ORDER BY
                (service_key IS NULL)::int
                + (action_type IS NULL)::int
                + (environment IS NULL)::int
                + (severity IS NULL)::int ASC,
                service_key NULLS LAST,
                action_type NULLS LAST
            LIMIT 500
            """
        )
        return [AutonomyConfigOut(**row) for row in cur.fetchall()]


@router.put("/autonomy-config", response_model=AutonomyConfigOut)
def upsert_autonomy_config(
    body: AutonomyConfigUpsert,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> AutonomyConfigOut:
    require_permission(principal, Permission.INCIDENT_WRITE)
    try:
        result = upsert_autonomy_config_command(
            conn,
            autonomy_level=body.autonomy_level,
            service_key=body.service_key,
            action_type=body.action_type,
            environment=body.environment,
            severity=body.severity,
            notes=body.notes,
            actor=principal.actor_id,
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AutonomyConfigOut(
        config_id=result.config_id,
        service_key=result.service_key,
        action_type=result.action_type,
        environment=result.environment,
        severity=result.severity,
        autonomy_level=result.autonomy_level,
        notes=result.notes,
        inserted=result.inserted,
    )


@router.get("/policies/{policy_key}/versions", response_model=list[PolicyVersionOut])
def list_policy_versions(
    policy_key: str,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> list[PolicyVersionOut]:
    """I7: policy version history (immutable snapshots)."""
    require_permission(principal, Permission.INCIDENT_READ)
    rows = list_policy_definitions(conn, policy_key=policy_key)
    return [
        PolicyVersionOut(
            policy_definition_id=r.policy_definition_id,
            policy_key=r.policy_key,
            version=r.version,
            version_label=r.version_label,
            body=r.body,
            notes=r.notes,
            created_by=r.created_by,
            active=r.active,
        )
        for r in rows
    ]


@router.post(
    "/policies/{policy_key}/versions",
    response_model=PolicyVersionOut,
    status_code=201,
)
def publish_policy_version(
    policy_key: str,
    body: PolicyVersionPublish,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> PolicyVersionOut:
    """I7 Admin: publish a new policy version (does not rewrite past decisions)."""
    require_permission(principal, Permission.ADMIN_CONFIG)
    result = publish_policy_version_command(
        conn,
        policy_key=policy_key,
        body=dict(body.body),
        notes=body.notes,
        created_by=principal.actor_id,
        activate=body.activate,
        commit=True,
    )
    return PolicyVersionOut(
        policy_definition_id=result.policy_definition_id,
        policy_key=result.policy_key,
        version=result.version,
        version_label=result.version_label,
        body=result.body,
        notes=result.notes,
        created_by=result.created_by,
        active=result.active,
    )


@router.post(
    "/policies/{policy_key}/versions/{version}/activate",
    response_model=PolicyActivateOut,
)
def activate_policy_version(
    policy_key: str,
    version: int,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> PolicyActivateOut:
    """I7 Admin: activate an existing immutable policy version."""
    require_permission(principal, Permission.ADMIN_CONFIG)
    try:
        result = activate_policy_version_command(
            conn,
            policy_key=policy_key,
            version=version,
            activated_by=principal.actor_id,
            commit=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PolicyActivateOut(
        policy_key=result.policy_key,
        version=result.version,
        version_label=result.version_label,
        activated_by=result.activated_by,
    )


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
    order: Literal["asc", "desc"] = Query(
        default="desc",
        description="Chronological order: asc = oldest first (readable chronicle).",
    ),
) -> list[TimelineEventOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    order_sql = "ASC" if order == "asc" else "DESC"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, incident_id, event_type, summary, actor, occurred_at, payload
            FROM domain.timeline_event
            WHERE incident_id = %s
            ORDER BY occurred_at {order_sql}, created_at {order_sql}
            LIMIT 200
            """,
            (str(incident_id),),
        )
        return [TimelineEventOut(**row) for row in cur.fetchall()]


@router.get("/incidents/{incident_id}/audit", response_model=list[AuditEventOut])
def list_audit(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
    order: Literal["asc", "desc"] = Query(
        default="desc",
        description="Chronological order: asc = oldest first.",
    ),
) -> list[AuditEventOut]:
    """L2: privileged who/what/when trail (not Timeline)."""
    require_permission(principal, Permission.INCIDENT_READ)
    order_sql = "ASC" if order == "asc" else "DESC"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, incident_id, action, actor, resource_type, resource_id,
                   outcome, occurred_at, details
            FROM domain.audit_event
            WHERE incident_id = %s
            ORDER BY occurred_at {order_sql}, created_at {order_sql}
            LIMIT 200
            """,
            (str(incident_id),),
        )
        return [AuditEventOut(**row) for row in cur.fetchall()]


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


@router.post(
    "/incidents/{incident_id}/postmortem/draft",
    response_model=PostmortemDraftOut,
    status_code=201,
)
def create_postmortem_draft(
    incident_id: UUID,
    body: PostmortemDraftCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> PostmortemDraftOut:
    """L4: grounded DRAFT after RESOLVED; uncited claims → 400."""
    require_permission(principal, Permission.INCIDENT_WRITE)
    claims = None
    if body.claims is not None:
        claims = [c.model_dump() for c in body.claims]
    try:
        result = create_postmortem_draft_command(
            conn,
            incident_id=incident_id,
            claims=claims,
            title=body.title,
            body_markdown=body.body_markdown,
            author=principal.actor_id,
            commit=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PostmortemNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PostmortemFinalImmutableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnsupportedClaimError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PostmortemDraftOut(
        postmortem_id=result.postmortem_id,
        incident_id=result.incident_id,
        status=result.status,
        title=result.title,
        claim_count=result.claim_count,
        cited_evidence_ids=list(result.cited_evidence_ids),
        inserted=result.inserted,
    )


@router.post(
    "/incidents/{incident_id}/postmortem/finalize",
    response_model=PostmortemFinalizeOut,
)
def finalize_postmortem(
    incident_id: UUID,
    body: PostmortemFinalize,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> PostmortemFinalizeOut:
    """L5: DRAFT → FINAL with corrective_actions[]; RESOLVED → POSTMORTEM."""
    require_permission(principal, Permission.INCIDENT_WRITE)
    try:
        result = finalize_postmortem_command(
            conn,
            incident_id=incident_id,
            corrective_actions=list(body.corrective_actions),
            actor=principal.actor_id,
            commit=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        PostmortemNotReadyError,
        PostmortemFinalImmutableError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PostmortemCorrectiveActionsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PostmortemFinalizeOut(
        postmortem_id=result.postmortem_id,
        incident_id=result.incident_id,
        status=result.status,
        corrective_actions=list(result.corrective_actions),
        incident_state=result.incident_state,
        incident_revision=result.incident_revision,
    )


@router.get(
    "/incidents/{incident_id}/postmortem/export",
    response_model=PostmortemExportOut,
)
def download_postmortem_export(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> PostmortemExportOut:
    """L6: download export package (timeline + evidence refs + postmortem body)."""
    require_permission(principal, Permission.INCIDENT_READ)
    try:
        result = export_postmortem_package_command(
            conn,
            incident_id=incident_id,
            actor=principal.actor_id,
            commit=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PostmortemExportOut(
        incident_id=result.incident_id,
        postmortem_id=result.postmortem_id,
        public_id=result.public_id,
        export_uri=result.export_uri,
        blob_status=result.blob_status,
        package=result.package,
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
