"""Auth stub until Epic C (OIDC + RBAC)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status


class Role(StrEnum):
    VIEWER = "viewer"
    RESPONDER = "responder"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class Principal:
    actor: str
    role: Role


def get_principal(
    authorization: Annotated[str | None, Header()] = None,
    x_actor: Annotated[str | None, Header(alias="X-Actor")] = None,
    x_role: Annotated[str | None, Header(alias="X-Role")] = None,
) -> Principal:
    """Accept `Authorization: Bearer local-dev` plus optional actor/role headers.

    401 if bearer missing/invalid. Role defaults to responder for local DX.
    Full OIDC/RBAC lands in C1/C2; 403 hooks use require_roles().
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid Authorization bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if token != "local-dev":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token (use local-dev until OIDC)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    role_raw = (x_role or Role.RESPONDER.value).lower()
    try:
        role = Role(role_raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"unknown role: {role_raw}",
        ) from exc

    return Principal(actor=x_actor or "local-user", role=role)


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
