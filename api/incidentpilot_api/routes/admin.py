"""M8: Admin surfaces — policies, runbooks, integrations (scope not secrets)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from psycopg.rows import dict_row

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.commands import (
    create_runbook_command,
    create_runbook_version_command,
    publish_runbook_version_command,
)
from incidentpilot_api.db import get_conn
from incidentpilot_api.integrations_status import list_integration_status
from incidentpilot_api.rbac import Permission, require_permission
from incidentpilot_api.schemas import (
    AdminRunbookCreate,
    AdminRunbookOut,
    AdminRunbookVersionCreate,
    AdminRunbookVersionOut,
    IntegrationStatusOut,
    PolicyKeyOut,
)

router = APIRouter(tags=["admin"])


@router.get(
    "/admin/policies",
    response_model=list[PolicyKeyOut],
    summary="Policy keys + active version (admin)",
)
def list_policy_keys(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> list[PolicyKeyOut]:
    require_permission(principal, Permission.ADMIN_CONFIG)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT d.policy_key,
                   COUNT(*)::int AS version_count,
                   MAX(d.version) AS latest_version,
                   (
                     SELECT a.version FROM domain.policy_active a
                     WHERE a.policy_key = d.policy_key
                   ) AS active_version
            FROM domain.policy_definition d
            GROUP BY d.policy_key
            ORDER BY d.policy_key
            """
        )
        rows = cur.fetchall()
    return [
        PolicyKeyOut(
            policy_key=str(r["policy_key"]),
            version_count=int(r["version_count"]),
            latest_version=int(r["latest_version"]),
            active_version=(
                None if r["active_version"] is None else int(r["active_version"])
            ),
        )
        for r in rows
    ]


@router.get(
    "/admin/runbooks",
    response_model=list[AdminRunbookOut],
    summary="Runbook catalog for admin publish",
)
def list_admin_runbooks(
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> list[AdminRunbookOut]:
    require_permission(principal, Permission.ADMIN_CONFIG)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT r.id, r.key, r.title, r.hypothesis_class, r.description,
                   r.active_version_id, s.key AS service_key,
                   av.version AS active_version,
                   av.status AS active_status,
                   av.allowed_action_types AS active_allowed_action_types
            FROM domain.runbook r
            LEFT JOIN domain.service s ON s.id = r.service_id
            LEFT JOIN domain.runbook_version av ON av.id = r.active_version_id
            ORDER BY r.key
            """
        )
        books = cur.fetchall()
        cur.execute(
            """
            SELECT id, runbook_id, version, status, allowed_action_types,
                   proposed_by, created_at
            FROM domain.runbook_version
            ORDER BY runbook_id, version DESC
            """
        )
        versions = cur.fetchall()
    by_rb: dict[str, list[AdminRunbookVersionOut]] = {}
    for v in versions:
        rid = str(v["runbook_id"])
        by_rb.setdefault(rid, []).append(
            AdminRunbookVersionOut(
                runbook_version_id=v["id"],
                runbook_id=v["runbook_id"],
                version=int(v["version"]),
                status=str(v["status"]),
                allowed_action_types=[str(a) for a in (v["allowed_action_types"] or [])],
                proposed_by=None if v["proposed_by"] is None else str(v["proposed_by"]),
                created_at=(
                    None if v["created_at"] is None else v["created_at"].isoformat()
                ),
            )
        )
    out: list[AdminRunbookOut] = []
    for r in books:
        rid = str(r["id"])
        allowed = r["active_allowed_action_types"] or []
        out.append(
            AdminRunbookOut(
                runbook_id=r["id"],
                key=str(r["key"]),
                title=str(r["title"]),
                hypothesis_class=(
                    None
                    if r["hypothesis_class"] is None
                    else str(r["hypothesis_class"])
                ),
                description=(
                    None if r["description"] is None else str(r["description"])
                ),
                service_key=(
                    None if r["service_key"] is None else str(r["service_key"])
                ),
                active_version_id=r["active_version_id"],
                active_version=(
                    None if r["active_version"] is None else int(r["active_version"])
                ),
                active_status=(
                    None if r["active_status"] is None else str(r["active_status"])
                ),
                active_allowed_action_types=[str(a) for a in list(allowed)],
                versions=by_rb.get(rid, []),
            )
        )
    return out


@router.post(
    "/admin/runbooks",
    response_model=AdminRunbookOut,
    status_code=201,
    summary="Create runbook (admin)",
)
def create_admin_runbook(
    body: AdminRunbookCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> AdminRunbookOut:
    require_permission(principal, Permission.ADMIN_CONFIG)
    try:
        created = create_runbook_command(
            conn,
            key=body.key,
            title=body.title,
            hypothesis_class=body.hypothesis_class,
            description=body.description,
            service_key=body.service_key,
            environment=body.environment,
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminRunbookOut(
        runbook_id=created.runbook_id,
        key=created.key,
        title=body.title.strip(),
        hypothesis_class=body.hypothesis_class,
        description=body.description,
        service_key=body.service_key,
        versions=[],
    )


@router.post(
    "/admin/runbooks/{runbook_id}/versions",
    response_model=AdminRunbookVersionOut,
    status_code=201,
    summary="Create draft runbook version (admin)",
)
def create_admin_runbook_version(
    runbook_id: UUID,
    body: AdminRunbookVersionCreate,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> AdminRunbookVersionOut:
    require_permission(principal, Permission.ADMIN_CONFIG)
    try:
        created = create_runbook_version_command(
            conn,
            runbook_id=runbook_id,
            body_markdown=body.body_markdown,
            allowed_action_types=body.allowed_action_types,
            proposed_by=principal.actor_id,
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminRunbookVersionOut(
        runbook_version_id=created.runbook_version_id,
        runbook_id=created.runbook_id,
        version=created.version,
        status=created.status,
        allowed_action_types=list(created.allowed_action_types),
        proposed_by=principal.actor_id,
    )


@router.post(
    "/admin/runbooks/versions/{runbook_version_id}/publish",
    response_model=AdminRunbookVersionOut,
    summary="Publish draft runbook version (admin)",
)
def publish_admin_runbook_version(
    runbook_version_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
    set_active: bool = True,
) -> AdminRunbookVersionOut:
    require_permission(principal, Permission.ADMIN_CONFIG)
    try:
        published = publish_runbook_version_command(
            conn,
            runbook_version_id=runbook_version_id,
            set_active=set_active,
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminRunbookVersionOut(
        runbook_version_id=published.runbook_version_id,
        runbook_id=published.runbook_id,
        version=published.version,
        status=published.status,
        allowed_action_types=list(published.allowed_action_types),
    )


@router.get(
    "/admin/integrations",
    response_model=list[IntegrationStatusOut],
    summary="Integration health/scope — never secrets (M8)",
)
def get_integrations(
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[IntegrationStatusOut]:
    require_permission(principal, Permission.ADMIN_CONFIG)
    return [IntegrationStatusOut.model_validate(r) for r in list_integration_status()]
