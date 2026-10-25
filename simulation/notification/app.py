"""Simulated notification service (E1)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field

from common.health import health_payload
from common.observability import instrument_app

app = FastAPI(title="sim-notification", version="0.1.0")
instrument_app(app, "notification")

_MESSAGES: list[dict[str, object]] = []


class NotifyIn(BaseModel):
    user_id: str = Field(min_length=1)
    channel: str = Field(default="email")
    template: str = Field(min_length=1)
    order_id: str = Field(min_length=1)


class NotifyOut(BaseModel):
    message_id: str
    status: str


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return health_payload("notification")


@app.post("/v1/messages", response_model=NotifyOut)
def send_message(body: NotifyIn) -> NotifyOut:
    message_id = f"msg_{uuid4().hex[:12]}"
    _MESSAGES.append(
        {
            "message_id": message_id,
            "user_id": body.user_id,
            "channel": body.channel,
            "template": body.template,
            "order_id": body.order_id,
            "status": "queued",
        }
    )
    return NotifyOut(message_id=message_id, status="queued")


@app.get("/v1/messages")
def list_messages() -> dict[str, object]:
    """Ops-style inbox peek for local demos — not an answer key."""
    return {"count": len(_MESSAGES), "messages": list(_MESSAGES)[-20:]}
