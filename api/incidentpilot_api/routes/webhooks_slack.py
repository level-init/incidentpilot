"""Slack interactive webhook ingress (K2/K3) — verify, persist, map approvals."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any
from urllib.parse import parse_qs
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from incidentpilot_api.db import database_url
from incidentpilot_api.slack_signing import VerifiedSlackBody, require_slack_signature
from incidentpilot_api.temporal import get_temporal_client
from incidentpilot_api.webhook_auth import new_ingress_id
from incidentpilot_shared import try_begin_idempotent
from incidentpilot_shared.slack_approval import map_slack_interaction_to_approval
from incidentpilot_shared.slack_ingress import persist_slack_interaction_command

router = APIRouter(prefix="/webhooks/slack", tags=["webhooks"])

_IDEM_SCOPE = "webhook:slack_interaction"


class SlackInteractionAccepted(BaseModel):
    """HTTP body for tests + Slack ephemeral ack (``text`` / ``response_type``)."""

    response_type: str = "ephemeral"
    text: str = Field(description="Visible Slack UX message")
    status: str = Field(description="accepted | duplicate | mapped | stale | failed")
    ingress_id: str
    interaction_id: UUID | None = None
    idempotent: bool = False
    interaction_type: str | None = None
    approval_mapped: bool = False
    workflow_signaled: bool = False
    code: str | None = None


def _parse_interaction_payload(raw_body: bytes) -> dict[str, Any]:
    """Slack sends ``application/x-www-form-urlencoded`` with a ``payload`` JSON field."""
    text = raw_body.decode("utf-8")
    if text.lstrip().startswith("{"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data
    form = parse_qs(text, keep_blank_values=True)
    if "payload" not in form or not form["payload"]:
        raise ValueError("missing form field 'payload'")
    data = json.loads(form["payload"][0])
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")
    return data


def _idem_key(payload: dict[str, Any], raw_body: bytes) -> tuple[str, str]:
    body_hash = hashlib.sha256(raw_body).hexdigest()
    trigger = payload.get("trigger_id")
    if trigger and str(trigger).strip():
        return f"trigger:{str(trigger).strip()}", body_hash
    return f"body:{body_hash}", body_hash


def _status_from_map(*, mapped_ok: bool, code: str | None, interaction_status: str) -> str:
    if code == "STALE_ACTION_VERSION":
        return "stale"
    if interaction_status == "MAPPED" and mapped_ok:
        return "mapped"
    if interaction_status == "FAILED":
        return "failed"
    return "accepted"


@router.post(
    "/interactions",
    response_model=SlackInteractionAccepted,
    status_code=status.HTTP_200_OK,
    summary="Slack interactive component ingress",
)
async def slack_interactions(
    verified: Annotated[VerifiedSlackBody, Depends(require_slack_signature)],
) -> SlackInteractionAccepted | JSONResponse:
    """Verify Slack signature, persist interaction, map approve/reject (K3).

    Invalid signatures never reach persistence (401). Valid payloads are written
    to ``domain.slack_interaction`` **before** the 200 response. Stale action
    versions return a visible ``STALE_ACTION_VERSION`` message (still HTTP 200
    so Slack shows the ephemeral text).
    """
    try:
        payload = _parse_interaction_payload(verified.raw)
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "invalid Slack interaction payload"},
        )

    key, request_hash = _idem_key(payload, verified.raw)
    ingress_id = new_ingress_id()

    try:
        temporal = await get_temporal_client()
    except Exception:  # noqa: BLE001 — outbox dispatcher remains fallback
        temporal = None

    with psycopg.connect(database_url()) as conn:
        first = try_begin_idempotent(
            conn,
            scope=_IDEM_SCOPE,
            key=key,
            request_hash=request_hash,
            response_ref={
                "ingress_id": ingress_id,
                "path": "/webhooks/slack/interactions",
            },
        )
        if not first:
            conn.commit()
            existing = None
            trigger = payload.get("trigger_id")
            if trigger and str(trigger).strip():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, interaction_type, status
                        FROM domain.slack_interaction
                        WHERE slack_trigger_id = %s
                        """,
                        (str(trigger).strip(),),
                    )
                    existing = cur.fetchone()
            return SlackInteractionAccepted(
                text="Duplicate Slack interaction (already processed).",
                status="duplicate",
                ingress_id=ingress_id,
                interaction_id=UUID(str(existing[0])) if existing else None,
                idempotent=True,
                interaction_type=str(existing[1]) if existing else None,
                approval_mapped=bool(existing and str(existing[2]) == "MAPPED"),
            )

        result = persist_slack_interaction_command(
            conn,
            payload=payload,
            request_timestamp=verified.timestamp,
            ingress_id=ingress_id,
            commit=True,
        )

        mapped = await map_slack_interaction_to_approval(
            conn,
            interaction_id=result.interaction_id,
            payload=payload,
            temporal_client=temporal,
            commit=True,
        )

    return SlackInteractionAccepted(
        text=mapped.visible_message,
        status=_status_from_map(
            mapped_ok=mapped.ok,
            code=mapped.code,
            interaction_status=mapped.interaction_status,
        ),
        ingress_id=ingress_id,
        interaction_id=result.interaction_id,
        idempotent=False,
        interaction_type=result.interaction_type,
        approval_mapped=mapped.interaction_status == "MAPPED",
        workflow_signaled=mapped.workflow_signaled,
        code=mapped.code,
    )
