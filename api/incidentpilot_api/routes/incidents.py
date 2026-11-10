from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection
from psycopg.rows import dict_row

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.commands import (
    PostmortemFinalRequiredError,
    create_incident_command,
    transition_incident_command,
)
from incidentpilot_api.db import get_conn, get_conn_with_permission
from incidentpilot_api.rbac import Permission, require_permission
from incidentpilot_api.schemas import (
    IncidentCreate,
    IncidentOut,
    IncidentTransition,
)
from incidentpilot_shared.domain.transitions import (
    IllegalTransitionError,
    IncidentState,
    StaleRevisionError,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])


def _row_to_incident(row: dict[str, object]) -> IncidentOut:
    severity = row["severity"]
    summary = row["summary"]
    return IncidentOut.model_validate(
        {
            "id": row["id"],
            "public_id": row["public_id"],
            "state": row["state"],
            "title": row["title"],
            "severity": None if severity is None else str(severity),
            "incident_revision": row["incident_revision"],
            "summary": None if summary is None else str(summary),
            "opened_at": row["opened_at"],
            "resolved_at": row["resolved_at"],
            "closed_at": row["closed_at"],
        }
    )


@router.get("", response_model=list[IncidentOut])
def list_incidents(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> list[IncidentOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, public_id, state, title, severity, incident_revision,
                   summary, opened_at, resolved_at, closed_at
            FROM domain.incident
            ORDER BY opened_at DESC
            LIMIT 100
            """
        )
        return [_row_to_incident(row) for row in cur.fetchall()]


@router.post("", response_model=IncidentOut, status_code=status.HTTP_201_CREATED)
def create_incident(
    body: IncidentCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn_with_permission(Permission.INCIDENT_WRITE))],
) -> IncidentOut:
    created = create_incident_command(
        conn,
        title=body.title,
        severity=body.severity,
        summary=body.summary,
        actor=principal.actor_id,
        commit=True,
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, public_id, state, title, severity, incident_revision,
                   summary, opened_at, resolved_at, closed_at
            FROM domain.incident WHERE id = %s
            """,
            (str(created.incident_id),),
        )
        row = cur.fetchone()
        assert row is not None
    return _row_to_incident(row)


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> IncidentOut:
    require_permission(principal, Permission.INCIDENT_READ)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, public_id, state, title, severity, incident_revision,
                   summary, opened_at, resolved_at, closed_at
            FROM domain.incident WHERE id = %s
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return _row_to_incident(row)


@router.post("/{incident_id}/transitions", response_model=IncidentOut)
def transition_incident(
    incident_id: UUID,
    body: IncidentTransition,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> IncidentOut:
    require_permission(principal, Permission.INCIDENT_WRITE)
    try:
        to_state = IncidentState(body.to_state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid to_state") from exc
    try:
        transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=body.expected_revision,
            to_state=to_state,
            actor=principal.actor_id,
            commit=True,
        )
    except StaleRevisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IllegalTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PostmortemFinalRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return get_incident(incident_id, principal, conn)
