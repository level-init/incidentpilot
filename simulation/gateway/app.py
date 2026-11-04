"""Simulated API gateway — orchestrates happy-path checkout (E1)."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.faults import install_faults
from common.health import health_payload
from common.observability import instrument_app

app = FastAPI(title="sim-gateway", version="0.1.0")
instrument_app(app, "gateway")
install_faults(app, "gateway")

# Unit price for demo SKUs (cents).
_PRICES = {
    "SKU-WIDGET": 2500,
    "SKU-GADGET": 4999,
}


def _url(name: str, default_port: int) -> str:
    env_key = f"SIM_{name.upper()}_URL"
    return os.environ.get(env_key, f"http://127.0.0.1:{default_port}")


def auth_url() -> str:
    return _url("auth", 8101)


def inventory_url() -> str:
    return _url("inventory", 8104)


def payment_url() -> str:
    return _url("payment", 8103)


def checkout_url() -> str:
    return _url("checkout", 8102)


def notification_url() -> str:
    return _url("notification", 8105)


class CheckoutIn(BaseModel):
    user_id: str = Field(default="user_demo")
    token: str = Field(default="tok_demo_user")
    sku: str = Field(default="SKU-WIDGET")
    quantity: int = Field(default=1, ge=1, le=10)
    card_last4: str = Field(default="4242", min_length=4, max_length=4)


class CheckoutOut(BaseModel):
    order_id: str
    status: str
    amount_cents: int
    charge_id: str
    reservation_id: str
    message_id: str


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return health_payload("gateway")


@app.get("/readyz")
def readyz() -> dict[str, object]:
    """Readiness for scenario baseline gate — probes upstream /healthz."""
    upstreams = {
        "auth": auth_url(),
        "checkout": checkout_url(),
        "payment": payment_url(),
        "inventory": inventory_url(),
        "notification": notification_url(),
    }
    checks: dict[str, object] = {}
    all_ok = True
    try:
        with httpx.Client(timeout=3.0) as client:
            for name, base in upstreams.items():
                try:
                    res = client.get(f"{base}/healthz")
                    body = (
                        res.json()
                        if res.headers.get("content-type", "").startswith("application/json")
                        else {}
                    )
                    ok = res.status_code == 200 and body.get("status") == "ok"
                    checks[name] = {
                        "ok": ok,
                        "status_code": res.status_code,
                        "body_status": body.get("status"),
                    }
                    if not ok:
                        all_ok = False
                except httpx.HTTPError as exc:
                    checks[name] = {"ok": False, "error": str(exc)}
                    all_ok = False
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"readyz probe failed: {exc}") from exc

    status = "ok" if all_ok else "error"
    payload = health_payload("gateway", status=status, checks=checks)
    if not all_ok:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.post("/v1/checkout", response_model=CheckoutOut)
def checkout(body: CheckoutIn) -> CheckoutOut:
    """Happy-path checkout across auth → inventory → payment → checkout → notify."""
    price = _PRICES.get(body.sku)
    if price is None:
        raise HTTPException(status_code=400, detail="unknown sku")
    amount_cents = price * body.quantity

    try:
        with httpx.Client(timeout=10.0) as client:
            auth = client.post(
                f"{auth_url()}/v1/sessions/validate",
                json={"user_id": body.user_id, "token": body.token},
            )
            if auth.status_code != 200:
                raise HTTPException(status_code=401, detail="auth failed")

            inv = client.post(
                f"{inventory_url()}/v1/reservations",
                json={"sku": body.sku, "quantity": body.quantity},
            )
            if inv.status_code != 200:
                raise HTTPException(status_code=409, detail=f"inventory: {inv.text}")
            reservation_id = str(inv.json()["reservation_id"])

            pay = client.post(
                f"{payment_url()}/v1/charges",
                json={
                    "amount_cents": amount_cents,
                    "currency": "USD",
                    "card_last4": body.card_last4,
                    "order_ref": f"pending-{body.user_id}",
                },
            )
            if pay.status_code != 200:
                raise HTTPException(status_code=402, detail=f"payment: {pay.text}")
            charge_id = str(pay.json()["charge_id"])

            order = client.post(
                f"{checkout_url()}/v1/orders",
                json={
                    "user_id": body.user_id,
                    "sku": body.sku,
                    "quantity": body.quantity,
                    "reservation_id": reservation_id,
                    "charge_id": charge_id,
                    "amount_cents": amount_cents,
                },
            )
            if order.status_code != 200:
                raise HTTPException(status_code=502, detail=f"checkout: {order.text}")
            order_body: dict[str, Any] = order.json()
            order_id = str(order_body["order_id"])

            notify = client.post(
                f"{notification_url()}/v1/messages",
                json={
                    "user_id": body.user_id,
                    "channel": "email",
                    "template": "order_confirmed",
                    "order_id": order_id,
                },
            )
            if notify.status_code != 200:
                raise HTTPException(status_code=502, detail=f"notify: {notify.text}")
            message_id = str(notify.json()["message_id"])
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"upstream unavailable: {exc}") from exc

    return CheckoutOut(
        order_id=order_id,
        status="confirmed",
        amount_cents=amount_cents,
        charge_id=charge_id,
        reservation_id=reservation_id,
        message_id=message_id,
    )
