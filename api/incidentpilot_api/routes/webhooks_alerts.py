"""Alert webhook ingress — Alertmanager auth, replay, normalize, correlate, workflow (F1–F5)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from psycopg import Connection
from pydantic import BaseModel, Field

from incidentpilot_api.commands import correlate_alert_command, upsert_alert_command
from incidentpilot_api.db import database_url
from incidentpilot_api.temporal import start_incident_workflows
from incidentpilot_api.webhook_auth import new_ingress_id, require_alertmanager_auth
from incidentpilot_shared import normalize_alertmanager_webhook, try_begin_idempotent

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
    alert_ids: list[UUID] = Field(default_factory=list)
    fingerprints: list[str] = Field(default_factory=list)
    incident_ids: list[UUID] = Field(default_factory=list)


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
    F2/F4: normalize, upsert alert, correlate by fingerprint/time/service.
    F5: after commit, idempotently start IncidentWorkflow → INVESTIGATING.
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
    if not first:
        conn.commit()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "duplicate",
                "ingress_id": ingress_id,
                "idempotent": True,
                "alert_ids": [],
                "fingerprints": [],
                "incident_ids": [],
            },
        )

    alert_ids: list[UUID] = []
    fingerprints: list[str] = []
    incident_ids: list[UUID] = []
    for normalized in normalize_alertmanager_webhook(payload):
        result = upsert_alert_command(
            conn,
            fingerprint=normalized.fingerprint,
            source=normalized.source,
            status=normalized.status,
            labels=normalized.labels,
            annotations=normalized.annotations,
            raw_payload=normalized.raw_payload,
            starts_at=normalized.starts_at,
            ends_at=normalized.ends_at,
            commit=False,
        )
        correlated = correlate_alert_command(
            conn,
            alert_id=result.alert_id,
            fingerprint=result.fingerprint,
            labels=normalized.labels,
            annotations=normalized.annotations,
            actor="alertmanager",
            commit=False,
        )
        alert_ids.append(result.alert_id)
        fingerprints.append(result.fingerprint)
        incident_ids.append(correlated.incident_id)

    conn.commit()
    await start_incident_workflows(incident_ids)
    return AlertIngressAccepted(
        status="accepted",
        ingress_id=ingress_id,
        idempotent=False,
        alert_ids=alert_ids,
        fingerprints=fingerprints,
        incident_ids=incident_ids,
    )
