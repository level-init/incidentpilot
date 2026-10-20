"""Human session-bound actions: observations + approval decisions (C1/C2)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.commands import (
    append_evidence_command,
    decide_approval_command,
)
from incidentpilot_api.db import get_conn
from incidentpilot_api.rbac import (
    Permission,
    assert_approval_allowed_by_policy,
    require_permission,
)
from incidentpilot_api.schemas import ApprovalOut, EvidenceOut

router = APIRouter(tags=["human"])


class HumanObservationCreate(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecideBody(BaseModel):
    status: str = Field(description="APPROVED or REJECTED")


@router.post(
    "/incidents/{incident_id}/observations",
    response_model=EvidenceOut,
    status_code=status.HTTP_201_CREATED,
)
def create_human_observation(
    incident_id: UUID,
    body: HumanObservationCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> EvidenceOut:
    """HUMAN_OBSERVATION evidence — actor_id from session, never from body."""
    require_permission(principal, Permission.OBSERVATION_WRITE)
    result = append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="HUMAN_OBSERVATION",
        fingerprint=f"human:{principal.actor_id}:{uuid4().hex}",
        summary=body.summary,
        producer=f"session:{principal.actor_id}",
        payload=body.payload,
        provenance={
            "actor_id": principal.actor_id,
            "auth_mode": principal.auth_mode,
            "source": "HUMAN_OBSERVATION",
        },
        commit=True,
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, evidence_key, incident_id, kind, summary, fingerprint,
                   observed_at, producer
            FROM domain.evidence WHERE id = %s
            """,
            (str(result.evidence_id),),
        )
        row = cur.fetchone()
    assert row is not None
    return EvidenceOut(**row)


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalOut)
def decide_approval(
    approval_id: UUID,
    body: ApprovalDecideBody,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> ApprovalOut:
    """Approval decision — session actor; gated by RBAC + PolicyDecision."""
    require_permission(principal, Permission.APPROVAL_DECIDE)
    if body.status not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=400, detail="status must be APPROVED or REJECTED")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT a.action_id, a.action_version, a.status AS approval_status,
                   pd.decision AS policy_decision
            FROM domain.approval a
            LEFT JOIN domain.policy_decision pd
              ON pd.action_id = a.action_id
             AND pd.action_version = a.action_version
            WHERE a.id = %s
            """,
            (str(approval_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if row["approval_status"] != "PENDING":
        raise HTTPException(status_code=409, detail="approval is not PENDING")

    assert_approval_allowed_by_policy(
        None if row["policy_decision"] is None else str(row["policy_decision"])
    )

    try:
        decide_approval_command(
            conn,
            action_id=UUID(str(row["action_id"])),
            action_version=int(row["action_version"]),
            status=body.status,
            decided_by=principal.actor_id,
            commit=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, action_id, action_version, status, decided_by
            FROM domain.approval WHERE id = %s
            """,
            (str(approval_id),),
        )
        out = cur.fetchone()
    assert out is not None
    return ApprovalOut(**out)
