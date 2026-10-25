"""Simulated inventory service (E1)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="sim-inventory", version="0.1.0")

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
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "inventory"}


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
