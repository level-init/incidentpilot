"""Slack interactive webhook ingress (K2) — verify HMAC, persist before 200."""

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
from incidentpilot_api.webhook_auth import new_ingress_id
from incidentpilot_shared import try_begin_idempotent
from incidentpilot_shared.slack_ingress import persist_slack_interaction_command

router = APIRouter(prefix="/webhooks/slack", tags=["webhooks"])

_IDEM_SCOPE = "webhook:slack_interaction"


class SlackInteractionAccepted(BaseModel):
    status: str = Field(description="accepted | duplicate")
    ingress_id: str
    interaction_id: UUID | None = None
    idempotent: bool = False
    interaction_type: str | None = None


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


@router.post(
    "/interactions",
    response_model=SlackInteractionAccepted,
    status_code=status.HTTP_200_OK,
    summary="Slack interactive component ingress",
)
async def slack_interactions(
    verified: Annotated[VerifiedSlackBody, Depends(require_slack_signature)],
) -> SlackInteractionAccepted | JSONResponse:
    """Verify Slack signature, persist interaction, then ack.

    Invalid signatures never reach persistence (401). Valid payloads are written
    to ``domain.slack_interaction`` **before** the 200 response. Approval mapping
    is K3.
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
                        SELECT id, interaction_type FROM domain.slack_interaction
                        WHERE slack_trigger_id = %s
                        """,
                        (str(trigger).strip(),),
                    )
                    existing = cur.fetchone()
            return SlackInteractionAccepted(
                status="duplicate",
                ingress_id=ingress_id,
                interaction_id=UUID(str(existing[0])) if existing else None,
                idempotent=True,
                interaction_type=str(existing[1]) if existing else None,
            )

        result = persist_slack_interaction_command(
            conn,
            payload=payload,
            request_timestamp=verified.timestamp,
            ingress_id=ingress_id,
            commit=True,
        )

    return SlackInteractionAccepted(
        status="accepted",
        ingress_id=ingress_id,
        interaction_id=result.interaction_id,
        idempotent=False,
        interaction_type=result.interaction_type,
    )
