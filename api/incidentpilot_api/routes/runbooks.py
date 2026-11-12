"""Runbook search + pin (H6). Authority = allowed_action_types, not prose."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import BaseModel

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.commands import pin_runbook_version_command
from incidentpilot_api.db import get_conn
from incidentpilot_api.rbac import Permission, require_permission
from incidentpilot_api.schemas import PinnedRunbookOut
from incidentpilot_shared.runbooks import retrieve_runbooks

router = APIRouter(tags=["runbooks"])


class RunbookHitOut(BaseModel):
    runbook_key: str
    title: str
    version_id: UUID
    version: int
    hypothesis_class: str | None = None
    allowed_action_types: list[str]
    rank: float


class RunbookPinBody(BaseModel):
    runbook_version_id: UUID


class RunbookPinOut(BaseModel):
    incident_id: UUID
    runbook_version_id: UUID
    evidence_id: UUID
    evidence_key: str
    allowed_action_types: list[str]


@router.get("/runbooks/search", response_model=list[RunbookHitOut])
def search_runbooks(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
    q: str = Query(min_length=1, max_length=1000),
    limit: int = Query(default=5, ge=1, le=20),
    hypothesis_class: str | None = None,
    service_key: str | None = None,
) -> list[RunbookHitOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    hits = retrieve_runbooks(
        conn,
        query=q,
        limit=limit,
        hypothesis_class=hypothesis_class,
        service_key=service_key,
        include_body=False,
    )
    return [
        RunbookHitOut(
            runbook_key=h.runbook_key,
            title=h.title,
            version_id=h.version_id,
            version=h.version,
            hypothesis_class=h.hypothesis_class,
            allowed_action_types=list(h.allowed_action_types),
            rank=h.rank,
        )
        for h in hits
    ]


@router.get(
    "/incidents/{incident_id}/runbook",
    response_model=PinnedRunbookOut,
    summary="Pinned runbook: allowed actions (authority) vs prose (untrusted)",
)
def get_pinned_runbook(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> PinnedRunbookOut:
    require_permission(principal, Permission.INCIDENT_READ)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT i.pinned_runbook_version_id,
                   r.key AS runbook_key, r.title,
                   rv.version, rv.allowed_action_types, rv.body_markdown
            FROM domain.incident i
            LEFT JOIN domain.runbook_version rv
              ON rv.id = i.pinned_runbook_version_id
            LEFT JOIN domain.runbook r ON r.id = rv.runbook_id
            WHERE i.id = %s
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="incident not found")
    pinned_id = row["pinned_runbook_version_id"]
    if pinned_id is None:
        return PinnedRunbookOut(pinned=False)
    allowed = row["allowed_action_types"] or []
    return PinnedRunbookOut(
        pinned=True,
        runbook_key=None if row["runbook_key"] is None else str(row["runbook_key"]),
        title=None if row["title"] is None else str(row["title"]),
        version=None if row["version"] is None else int(row["version"]),
        runbook_version_id=pinned_id,
        allowed_action_types=[str(a) for a in list(allowed)],
        body_markdown=(None if row["body_markdown"] is None else str(row["body_markdown"])),
    )


@router.post("/incidents/{incident_id}/runbook-pin", response_model=RunbookPinOut)
def pin_runbook(
    incident_id: UUID,
    body: RunbookPinBody,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> RunbookPinOut:
    require_permission(principal, Permission.INCIDENT_WRITE)
    result = pin_runbook_version_command(
        conn,
        incident_id=incident_id,
        runbook_version_id=body.runbook_version_id,
        actor=principal.actor_id,
        commit=True,
    )
    return RunbookPinOut(
        incident_id=result.incident_id,
        runbook_version_id=result.runbook_version_id,
        evidence_id=result.evidence_id,
        evidence_key=result.evidence_key,
        allowed_action_types=list(result.allowed_action_types),
    )
