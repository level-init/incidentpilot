"""Simulated checkout / order service (E1)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.observability import instrument_app

app = FastAPI(title="sim-checkout", version="0.1.0")
instrument_app(app, "checkout")

_ORDERS: dict[str, dict[str, object]] = {}


class CreateOrderIn(BaseModel):
    user_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    reservation_id: str = Field(min_length=1)
    charge_id: str = Field(min_length=1)
    amount_cents: int = Field(ge=1)


class OrderOut(BaseModel):
    order_id: str
    status: str
    user_id: str
    sku: str
    quantity: int
    amount_cents: int


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "checkout"}


@app.post("/v1/orders", response_model=OrderOut)
def create_order(body: CreateOrderIn) -> OrderOut:
    order_id = f"ord_{uuid4().hex[:12]}"
    order = {
        "order_id": order_id,
        "status": "confirmed",
        "user_id": body.user_id,
        "sku": body.sku,
        "quantity": body.quantity,
        "amount_cents": body.amount_cents,
        "reservation_id": body.reservation_id,
        "charge_id": body.charge_id,
    }
    _ORDERS[order_id] = order
    return OrderOut(
        order_id=order_id,
        status="confirmed",
        user_id=body.user_id,
        sku=body.sku,
        quantity=body.quantity,
        amount_cents=body.amount_cents,
    )


@app.get("/v1/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: str) -> OrderOut:
    order = _ORDERS.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return OrderOut(
        order_id=str(order["order_id"]),
        status=str(order["status"]),
        user_id=str(order["user_id"]),
        sku=str(order["sku"]),
        quantity=int(order["quantity"]),  # type: ignore[arg-type]
        amount_cents=int(order["amount_cents"]),  # type: ignore[arg-type]
    )
