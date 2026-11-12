"""M7: Contextual manual resolve — RECOVERED→RESOLVED with reason + audit."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection
from psycopg.rows import dict_row

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.commands import (
    ManualResolveNotAllowed,
    manual_resolve_incident_command,
)
from incidentpilot_api.db import get_conn, get_conn_with_permission
from incidentpilot_api.rbac import Permission, require_permission
from incidentpilot_api.schemas import (
    ManualResolveBody,
    ManualResolveOut,
    ResolveContextOut,
    ResolveHealthOut,
)
from incidentpilot_shared.domain.transitions import (
    IllegalTransitionError,
    IncidentState,
    StaleRevisionError,
)

router = APIRouter(tags=["resolve"])


def _health(conn: Connection, incident_id: UUID) -> ResolveHealthOut | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT outcome, criteria, observations, decided_at
            FROM domain.validation_result
            WHERE incident_id = %s
            ORDER BY decided_at DESC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
    if row is None:
        return None
    decided = row["decided_at"]
    return ResolveHealthOut(
        outcome=str(row["outcome"]),
        criteria=dict(row["criteria"] or {}),
        observations=dict(row["observations"] or {}),
        decided_at=None if decided is None else decided.isoformat(),
    )


@router.get(
    "/incidents/{incident_id}/resolve-context",
    response_model=ResolveContextOut,
    summary="When contextual manual resolve is allowed (no generic Resolve)",
)
def get_resolve_context(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> ResolveContextOut:
    require_permission(principal, Permission.INCIDENT_READ)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT state, incident_revision, public_id
            FROM domain.incident WHERE id = %s
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="incident not found")
    state = str(row["state"])
    rev = int(row["incident_revision"])
    health = _health(conn, incident_id)
    eligible = state == IncidentState.RECOVERED.value
    if eligible:
        message = (
            "Manual resolve is available after validation marked RECOVERED. "
            "Provide a reason; this path is audited."
        )
    else:
        message = (
            f"Manual resolve is hidden for state `{state}` "
            "(requires RECOVERED). Use the automated validation path — "
            "there is no generic Resolve control."
        )
    return ResolveContextOut(
        eligible=eligible,
        current_state=state,
        incident_revision=rev,
        reason_required=True,
        message=message,
        health=health,
    )


@router.post(
    "/incidents/{incident_id}/resolve",
    response_model=ManualResolveOut,
    summary="Contextual manual resolve with reason + audit (M7)",
)
def post_manual_resolve(
    incident_id: UUID,
    body: ManualResolveBody,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[
        Connection, Depends(get_conn_with_permission(Permission.INCIDENT_WRITE))
    ],
) -> ManualResolveOut:
    try:
        result = manual_resolve_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=body.expected_revision,
            reason=body.reason,
            actor=principal.actor_id,
            commit=True,
        )
    except ManualResolveNotAllowed as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except StaleRevisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IllegalTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT public_id FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        pub = cur.fetchone()
    assert pub is not None
    return ManualResolveOut(
        incident_id=incident_id,
        public_id=str(pub["public_id"]),
        from_state=result.from_state.value,
        to_state=result.to_state.value,
        previous_revision=result.previous_revision,
        new_revision=result.new_revision,
        reason=body.reason.strip(),
        audited=True,
    )
