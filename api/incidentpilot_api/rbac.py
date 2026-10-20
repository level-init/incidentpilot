"""Ops RBAC: Viewer / Responder / Admin (C2).

Admin is powerful for configuration but **cannot** override a PolicyDecision
of BLOCK on remediation approvals (product non-negotiable).
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException, status

from incidentpilot_api.auth import Principal, Role


class Permission(StrEnum):
    INCIDENT_READ = "incident:read"
    INCIDENT_WRITE = "incident:write"
    OBSERVATION_WRITE = "observation:write"
    APPROVAL_DECIDE = "approval:decide"
    ADMIN_CONFIG = "admin:config"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({Permission.INCIDENT_READ}),
    Role.RESPONDER: frozenset(
        {
            Permission.INCIDENT_READ,
            Permission.INCIDENT_WRITE,
            Permission.OBSERVATION_WRITE,
            Permission.APPROVAL_DECIDE,
        }
    ),
    Role.ADMIN: frozenset(
        {
            Permission.INCIDENT_READ,
            Permission.INCIDENT_WRITE,
            Permission.OBSERVATION_WRITE,
            Permission.APPROVAL_DECIDE,
            Permission.ADMIN_CONFIG,
        }
    ),
}


def has_permission(principal: Principal, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(principal.role, frozenset())


def require_permission(principal: Principal, permission: Permission) -> None:
    if not has_permission(principal, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"role {principal.role} lacks permission {permission}",
        )


def assert_approval_allowed_by_policy(decision: str | None) -> None:
    """Gate approval decisions on PolicyDecision.

    - BLOCK: never approvable (including Admin) — no silent override
    - REQUIRE_APPROVAL: approvable by Responder/Admin (permission checked separately)
    - ALLOW_AUTONOMOUS: approval endpoint not applicable
    - missing: treat as not approvable until policy runs
    """
    if decision == "BLOCK":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("PolicyDecision is BLOCK; approval is forbidden (Admin cannot override BLOCK)"),
        )
    if decision == "ALLOW_AUTONOMOUS":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PolicyDecision is ALLOW_AUTONOMOUS; human approval not required",
        )
    if decision != "REQUIRE_APPROVAL":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no REQUIRE_APPROVAL PolicyDecision for this action version",
        )
