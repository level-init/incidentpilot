"""Service dependency / topology map (M11) — Postgres catalog, not Neo4j."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection

from incidentpilot_api.db import get_conn_with_permission
from incidentpilot_api.rbac import Permission
from incidentpilot_api.schemas import DependencyMapOut
from incidentpilot_shared.domain.dependencies import (
    build_dependency_map,
    incident_service_keys,
)

router = APIRouter(tags=["topology"])


@router.get("/topology/dependencies", response_model=DependencyMapOut)
def get_topology_dependencies(
    conn: Annotated[
        Connection, Depends(get_conn_with_permission(Permission.INCIDENT_READ))
    ],
    environment: str = Query(default="local", min_length=1, max_length=64),
) -> dict[str, Any]:
    """Catalog service dependency graph for the environment."""
    return build_dependency_map(conn, environment=environment)


@router.get(
    "/incidents/{incident_id}/dependency-map",
    response_model=DependencyMapOut,
)
def get_incident_dependency_map(
    incident_id: UUID,
    conn: Annotated[
        Connection, Depends(get_conn_with_permission(Permission.INCIDENT_READ))
    ],
    environment: str = Query(default="local", min_length=1, max_length=64),
) -> dict[str, Any]:
    """Incident overlay: linked services + 1-hop upstream/downstream propagation."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="incident not found")
    linked = incident_service_keys(conn, incident_id=incident_id)
    return build_dependency_map(
        conn, environment=environment, linked_keys=linked
    )
