"""Eval-only routes (C3) + Approval harness (I6).

GroundTruth requires eval entitlement. The approval harness also requires
eval entitlement and writes **real** ``domain.approval`` decisions (no Slack).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.db import get_conn, get_eval_conn_with_entitlement
from incidentpilot_api.rbac import (
    assert_approval_allowed_by_policy,
    require_eval_entitlement,
)
from incidentpilot_api.schemas import ApprovalOut
from incidentpilot_api.temporal import get_temporal_client
from incidentpilot_shared.approval_harness import harness_decide_approval

router = APIRouter(prefix="/eval", tags=["eval"])


class GroundTruthOut(BaseModel):
    id: UUID
    scenario_key: str
    answer_payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class HarnessDecideBody(BaseModel):
    status: str = Field(description="APPROVED or REJECTED")


class HarnessDecideOut(BaseModel):
    approval: ApprovalOut
    incident_id: UUID
    action_status: str
    decided_by: str
    noop: bool
    workflow_signaled: bool
    signal_error: str | None = None


@router.get("/ground-truth", response_model=list[GroundTruthOut])
def list_ground_truth(
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
    scenario_key: str | None = Query(default=None),
) -> list[GroundTruthOut]:
    """Read GroundTruth — requires eval entitlement (not ops Admin/Responder)."""
    sql = """
        SELECT id, scenario_key, answer_payload, created_at
        FROM eval.ground_truth
    """
    params: list[object] = []
    if scenario_key is not None:
        sql += " WHERE scenario_key = %s"
        params.append(scenario_key)
    sql += " ORDER BY created_at DESC LIMIT 100"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [GroundTruthOut(**row) for row in cur.fetchall()]


@router.post(
    "/approvals/{approval_id}/decide",
    response_model=HarnessDecideOut,
)
async def harness_decide_approval_route(
    approval_id: UUID,
    body: HarnessDecideBody,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> HarnessDecideOut:
    """I6 eval/test harness — real ApprovalDecision + workflow signal.

    Requires ``eval_entitled`` (ops Responder alone is not enough). Uses the
    domain decide command (same rows as human decide) and signals
    ``approval_decision`` so ``wait_for_approval`` resumes.
    """
    require_eval_entitlement(principal)
    if body.status not in {"APPROVED", "REJECTED"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must be APPROVED or REJECTED",
        )

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT a.status AS approval_status, pd.decision AS policy_decision
            FROM domain.approval a
            LEFT JOIN domain.policy_decision pd
              ON pd.action_id = a.action_id
             AND pd.action_version = a.action_version
            WHERE a.id = %s
            """,
            (str(approval_id),),
        )
        gate = cur.fetchone()
    if gate is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if gate["approval_status"] != "PENDING" and gate["approval_status"] != body.status:
        raise HTTPException(status_code=409, detail="approval is not PENDING")
    assert_approval_allowed_by_policy(
        None if gate["policy_decision"] is None else str(gate["policy_decision"])
    )

    try:
        client = await get_temporal_client()
    except Exception:  # noqa: BLE001 — harness still records domain decision
        client = None

    try:
        result = await harness_decide_approval(
            conn,
            approval_id=approval_id,
            status=body.status,
            decided_by=principal.actor_id,
            temporal_client=client,
            commit=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, action_id, action_version, status, decided_by
            FROM domain.approval WHERE id = %s
            """,
            (str(result.approval_id),),
        )
        out = cur.fetchone()
    assert out is not None
    return HarnessDecideOut(
        approval=ApprovalOut(**out),
        incident_id=result.incident_id,
        action_status=result.action_status,
        decided_by=result.decided_by,
        noop=result.noop,
        workflow_signaled=result.workflow_signaled,
        signal_error=result.signal_error,
    )
