"""Simulated inventory service (E1)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.health import health_payload
from common.observability import instrument_app

app = FastAPI(title="sim-inventory", version="0.1.0")
instrument_app(app, "inventory")

_STOCK: dict[str, int] = {
    "SKU-WIDGET": 100,
    "SKU-GADGET": 50,
}
_RESERVATIONS: dict[str, dict[str, object]] = {}


class ReserveIn(BaseModel):
    sku: str = Field(min_length=1)
    quantity: int = Field(ge=1, le=100)


class ReserveOut(BaseModel):
    reservation_id: str
    sku: str
    quantity: int
    remaining: int


@app.get("/healthz")
def healthz() -> dict[str, object]:
    stock_total = sum(_STOCK.values())
    # Degraded (still 200) when stock is exhausted — baseline gate checks status==ok.
    status = "ok" if stock_total > 0 else "degraded"
    return health_payload("inventory", status=status, stock_total=stock_total)


@app.get("/v1/stock/{sku}")
def get_stock(sku: str) -> dict[str, object]:
    if sku not in _STOCK:
        raise HTTPException(status_code=404, detail="unknown sku")
    return {"sku": sku, "available": _STOCK[sku]}


@app.post("/v1/reservations", response_model=ReserveOut)
def reserve(body: ReserveIn) -> ReserveOut:
    available = _STOCK.get(body.sku)
    if available is None:
        raise HTTPException(status_code=404, detail="unknown sku")
    if available < body.quantity:
        raise HTTPException(status_code=409, detail="insufficient stock")
    _STOCK[body.sku] = available - body.quantity
    reservation_id = f"res_{uuid4().hex[:12]}"
    _RESERVATIONS[reservation_id] = {
        "sku": body.sku,
        "quantity": body.quantity,
    }
    return ReserveOut(
        reservation_id=reservation_id,
        sku=body.sku,
        quantity=body.quantity,
        remaining=_STOCK[body.sku],
    )
