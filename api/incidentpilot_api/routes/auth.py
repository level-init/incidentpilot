"""Session introspection for the web shell (M1) — Bearer → Principal."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.schemas import SessionOut

router = APIRouter(tags=["auth"])


@router.get(
    "/auth/me",
    response_model=SessionOut,
    summary="Current session principal (ops role + eval flag)",
)
def auth_me(
    principal: Annotated[Principal, Depends(get_principal)],
) -> SessionOut:
    """Return the authenticated principal. No login endpoint — Bearer only."""
    return SessionOut(
        actor_id=principal.actor_id,
        role=principal.role.value,
        auth_mode=principal.auth_mode,
        email=principal.email,
        eval_entitled=principal.eval_entitled,
    )
