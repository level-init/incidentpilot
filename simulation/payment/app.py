"""Simulated payment service (E1)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.observability import instrument_app

app = FastAPI(title="sim-payment", version="0.1.0")
instrument_app(app, "payment")


class ChargeIn(BaseModel):
    amount_cents: int = Field(ge=1)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    card_last4: str = Field(min_length=4, max_length=4)
    order_ref: str = Field(min_length=1)


class ChargeOut(BaseModel):
    charge_id: str
    status: str
    amount_cents: int
    currency: str


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "payment"}


@app.post("/v1/charges", response_model=ChargeOut)
def charge(body: ChargeIn) -> ChargeOut:
    # Demo decline rule (not a root-cause oracle).
    if body.card_last4 == "0000":
        raise HTTPException(status_code=402, detail="card declined")
    return ChargeOut(
        charge_id=f"ch_{uuid4().hex[:12]}",
        status="captured",
        amount_cents=body.amount_cents,
        currency=body.currency.upper(),
    )
