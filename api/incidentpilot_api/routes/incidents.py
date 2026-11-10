from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
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

_INCIDENT_SELECT = """
SELECT i.id, i.public_id, i.state, i.title, i.severity, i.incident_revision,
       i.summary, i.opened_at, i.resolved_at, i.closed_at,
       COALESCE(
         array_agg(s.key ORDER BY s.key) FILTER (WHERE s.key IS NOT NULL),
         '{}'::text[]
       ) AS service_keys
FROM domain.incident i
LEFT JOIN domain.incident_service isv ON isv.incident_id = i.id
LEFT JOIN domain.service s ON s.id = isv.service_id
"""


def _row_to_incident(row: dict[str, object]) -> IncidentOut:
    severity = row["severity"]
    summary = row["summary"]
    raw_keys = row.get("service_keys") or []
    if isinstance(raw_keys, str):
        service_keys = [raw_keys] if raw_keys else []
    else:
        service_keys = [str(k) for k in list(raw_keys)]
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
            "service_keys": service_keys,
        }
    )


@router.get("", response_model=list[IncidentOut])
def list_incidents(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
    state: Annotated[str | None, Query(description="Exact incident state")] = None,
    severity: Annotated[str | None, Query(description="Exact severity")] = None,
    service: Annotated[str | None, Query(description="Linked service key (exact)")] = None,
) -> list[IncidentOut]:
    """Overview list — severity / state / service / timestamps for duration."""
    require_permission(principal, Permission.INCIDENT_READ)
    clauses: list[str] = []
    params: list[object] = []
    if state:
        clauses.append("i.state = %s")
        params.append(state)
    if severity:
        clauses.append("i.severity = %s")
        params.append(severity)
    if service:
        clauses.append(
            """
            EXISTS (
              SELECT 1
              FROM domain.incident_service isf
              JOIN domain.service sf ON sf.id = isf.service_id
              WHERE isf.incident_id = i.id AND sf.key = %s
            )
            """
        )
        params.append(service)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        {_INCIDENT_SELECT}
        {where}
        GROUP BY i.id
        ORDER BY i.opened_at DESC
        LIMIT 100
        """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
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
        service_key=body.service_key,
        actor=principal.actor_id,
        commit=True,
    )
    return get_incident(created.incident_id, principal, conn)


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> IncidentOut:
    require_permission(principal, Permission.INCIDENT_READ)
    sql = f"""
        {_INCIDENT_SELECT}
        WHERE i.id = %s
        GROUP BY i.id
        """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (str(incident_id),))
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
