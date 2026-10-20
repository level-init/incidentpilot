"""Read endpoints for alerts, evidence, hypotheses, actions, approvals, timeline, postmortem."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from psycopg.rows import dict_row

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.db import get_conn
from incidentpilot_api.rbac import Permission, require_permission
from incidentpilot_api.schemas import (
    ActionOut,
    AlertOut,
    ApprovalOut,
    EvidenceOut,
    HypothesisOut,
    PostmortemOut,
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
        SELECT id, incident_id, status, statement, proposed_by, confidence
        FROM domain.hypothesis
    """
    params: list[object] = []
    if incident_id is not None:
        sql += " WHERE incident_id = %s"
        params.append(str(incident_id))
    sql += " ORDER BY created_at DESC LIMIT 100"
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
