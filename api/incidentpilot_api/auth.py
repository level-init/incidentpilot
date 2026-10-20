"""Session identity (C1).

Contract is identical for local stub and future OIDC:
- `actor_id` is bound from the verified session/token only
- Clients must never supply `actor_id` / `actor` / `decided_by` in bodies
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

from fastapi import Depends, Header, HTTPException, Request, status


class Role(StrEnum):
    VIEWER = "viewer"
    RESPONDER = "responder"
    ADMIN = "admin"


AuthMode = Literal["stub", "oidc"]


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated session principal — source of human provenance."""

    actor_id: str
    role: Role
    auth_mode: AuthMode
    email: str | None = None

    @property
    def actor(self) -> str:
        """Legacy alias used by timeline/outbox fields."""
        return self.actor_id


# Local stub token → session map (AUTH_MODE=stub). OIDC replaces resolve_principal().
_STUB_SESSIONS: dict[str, Principal] = {
    "local-dev": Principal(
        actor_id="user_local_dev",
        role=Role.RESPONDER,
        auth_mode="stub",
        email="local-dev@incidentpilot.local",
    ),
    "local-dev-admin": Principal(
        actor_id="user_local_admin",
        role=Role.ADMIN,
        auth_mode="stub",
        email="admin@incidentpilot.local",
    ),
    "local-dev-viewer": Principal(
        actor_id="user_local_viewer",
        role=Role.VIEWER,
        auth_mode="stub",
        email="viewer@incidentpilot.local",
    ),
}


FORBIDDEN_CLIENT_IDENTITY_FIELDS = frozenset({"actor_id", "actor", "decided_by", "observed_by"})


def auth_mode() -> AuthMode:
    mode = os.environ.get("AUTH_MODE", "stub").lower()
    if mode not in {"stub", "oidc"}:
        return "stub"
    return mode  # type: ignore[return-value]


def _resolve_stub(token: str) -> Principal:
    principal = _STUB_SESSIONS.get(token)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "unknown stub token; use Bearer local-dev | local-dev-admin | "
                "local-dev-viewer (see docs/auth.md)"
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def _resolve_oidc(token: str) -> Principal:
    """Placeholder for Epic C OIDC validation — same Principal contract."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="AUTH_MODE=oidc is not wired yet; use AUTH_MODE=stub (docs/auth.md)",
    )


def resolve_bearer_token(token: str) -> Principal:
    if auth_mode() == "oidc":
        return _resolve_oidc(token)
    return _resolve_stub(token)


def get_principal(
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Bind Principal from Authorization bearer only (no client actor headers)."""
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid Authorization bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="empty bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return resolve_bearer_token(token)


async def reject_spoofed_identity(request: Request) -> None:
    """Reject client-supplied identity fields on JSON bodies (C1)."""
    if request.method not in {"POST", "PUT", "PATCH"}:
        return
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        return
    try:
        body: Any = await request.json()
    except Exception:
        return
    if not isinstance(body, dict):
        return
    spoofed = FORBIDDEN_CLIENT_IDENTITY_FIELDS.intersection(body.keys())
    if spoofed:
        fields = ", ".join(sorted(spoofed))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"client-supplied identity field(s) forbidden: {fields}; "
                "actor_id is bound from the authenticated session only"
            ),
        )


def require_roles(*allowed: Role) -> Callable[..., Principal]:
    allowed_set = set(allowed)

    def _dep(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if principal.role is Role.ADMIN or principal.role in allowed_set:
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"role {principal.role} not permitted",
        )

    return _dep
