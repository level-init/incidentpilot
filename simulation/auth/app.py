"""Simulated auth service (E1)."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.observability import instrument_app

app = FastAPI(title="sim-auth", version="0.1.0")
instrument_app(app, "auth")

# In-memory demo users — not GroundTruth / not an oracle.
_USERS = {
    "user_demo": {"display_name": "Demo Shopper", "token": "tok_demo_user"},
}


class SessionValidateIn(BaseModel):
    user_id: str = Field(min_length=1)
    token: str = Field(min_length=1)


class SessionValidateOut(BaseModel):
    user_id: str
    display_name: str
    valid: bool


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "auth"}


@app.post("/v1/sessions/validate", response_model=SessionValidateOut)
def validate_session(body: SessionValidateIn) -> SessionValidateOut:
    user = _USERS.get(body.user_id)
    if user is None or user["token"] != body.token:
        raise HTTPException(status_code=401, detail="invalid session")
    return SessionValidateOut(
        user_id=body.user_id,
        display_name=str(user["display_name"]),
        valid=True,
    )
