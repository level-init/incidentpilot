"""Alert webhook ingress (F1) — Alertmanager auth + replay defenses.

Normalization / IncidentWorkflow signaling land in F2+.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from psycopg import Connection
from pydantic import BaseModel, Field

from incidentpilot_api.db import database_url
from incidentpilot_api.webhook_auth import new_ingress_id, require_alertmanager_auth
from incidentpilot_shared import try_begin_idempotent

router = APIRouter(prefix="/webhooks/alerts", tags=["webhooks"])

_IDEM_SCOPE = "webhook:alertmanager"


def _conn_after_auth(
    _: Annotated[None, Depends(require_alertmanager_auth)],
) -> Iterator[psycopg.Connection]:
    """Open Postgres only after Alertmanager auth succeeds (401 without DB)."""
    with psycopg.connect(database_url()) as conn:
        yield conn


class AlertIngressAccepted(BaseModel):
    status: str = Field(description="accepted | duplicate")
    ingress_id: str
    idempotent: bool = False


def _replay_key(
    *,
    idempotency_key: str | None,
    request_id: str | None,
    body: dict[str, Any],
) -> tuple[str, str]:
    """Return (idempotency key, request_hash). Prefer client keys, else body hash."""
    raw = json.dumps(body, sort_keys=True, default=str, separators=(",", ":"))
    body_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if idempotency_key and idempotency_key.strip():
        return idempotency_key.strip(), body_hash
    if request_id and request_id.strip():
        return request_id.strip(), body_hash
    return f"body:{body_hash}", body_hash


@router.post(
    "/alertmanager",
    response_model=AlertIngressAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Alertmanager webhook ingress",
)
async def alertmanager_webhook(
    request: Request,
    conn: Annotated[Connection, Depends(_conn_after_auth)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    x_request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
) -> AlertIngressAccepted | JSONResponse:
    """Accept an Alertmanager webhook payload.

    Auth: Bearer / Basic / custom header (see docs/alert-webhooks.md).
    Replay: ``Idempotency-Key`` or ``X-Request-Id``, else SHA-256 of body.
    Duplicate keys return **200** with ``status=duplicate`` (success/no-op).
    """
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "request body must be JSON"},
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "request body must be a JSON object"},
        )

    key, request_hash = _replay_key(
        idempotency_key=idempotency_key,
        request_id=x_request_id,
        body=payload,
    )
    ingress_id = new_ingress_id()
    first = try_begin_idempotent(
        conn,
        scope=_IDEM_SCOPE,
        key=key,
        request_hash=request_hash,
        response_ref={"ingress_id": ingress_id, "path": "/webhooks/alerts/alertmanager"},
    )
    conn.commit()

    if not first:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "duplicate",
                "ingress_id": ingress_id,
                "idempotent": True,
            },
        )

    # F1: ingress only. F2 persists normalized Alert + fingerprint.
    return AlertIngressAccepted(
        status="accepted",
        ingress_id=ingress_id,
        idempotent=False,
    )
