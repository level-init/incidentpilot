"""Historical incident/postmortem search — suggestions only (H9)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import Connection
from pydantic import BaseModel, Field

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.db import get_conn
from incidentpilot_api.rbac import Permission, require_permission
from incidentpilot_shared.history import retrieve_historical_assist

router = APIRouter(tags=["history"])


class HistoricalHitOut(BaseModel):
    suggestion_id: str
    incident_id: UUID
    public_id: str
    title: str
    state: str
    rank: float
    postmortem_title: str | None = None
    snippet: str | None = None
    authoritative: bool = False
    may_cite_as_evidence: bool = False


class HistoricalSearchOut(BaseModel):
    query: str
    authoritative: bool = False
    may_cite_as_evidence: bool = False
    disclaimer: str = Field(
        default=(
            "Historical hits are suggestions only — not Evidence. "
            "Cite EV-… from the current incident after new collection."
        )
    )
    hits: list[HistoricalHitOut]


@router.get("/history/search", response_model=HistoricalSearchOut)
def search_history(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
    q: str = Query(min_length=1, max_length=1000),
    limit: int = Query(default=5, ge=1, le=20),
    exclude_incident_id: UUID | None = None,
) -> HistoricalSearchOut:
    require_permission(principal, Permission.INCIDENT_READ)
    hits = retrieve_historical_assist(
        conn,
        query=q,
        limit=limit,
        exclude_incident_id=exclude_incident_id,
    )
    return HistoricalSearchOut(
        query=q,
        authoritative=False,
        may_cite_as_evidence=False,
        hits=[
            HistoricalHitOut(
                suggestion_id=h.suggestion_id,
                incident_id=h.incident_id,
                public_id=h.public_id,
                title=h.title,
                state=h.state,
                rank=h.rank,
                postmortem_title=h.postmortem_title,
                snippet=h.snippet,
                authoritative=False,
                may_cite_as_evidence=False,
            )
            for h in hits
        ],
    )
