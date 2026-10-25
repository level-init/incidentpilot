"""E1: simulation service skeletons + no GroundTruth cheat routes."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "simulation"
if str(SIM) not in sys.path:
    sys.path.insert(0, str(SIM))

from common.contract import (  # noqa: E402
    FORBIDDEN_PATH_MARKERS,
    assert_no_forbidden_routes,
    path_is_forbidden,
    scan_apps,
)

SERVICES = ("auth", "checkout", "payment", "inventory", "notification", "gateway")


def _app(name: str):
    return importlib.import_module(f"{name}.app").app


@pytest.mark.parametrize("name", SERVICES)
def test_healthz(name: str) -> None:
    client = TestClient(_app(name))
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["service"] == name


@pytest.mark.parametrize("name", SERVICES)
def test_no_forbidden_routes(name: str) -> None:
    assert_no_forbidden_routes(_app(name), service=name)


def test_contract_scan_all_services_clean() -> None:
    apps = [(n, _app(n)) for n in SERVICES]
    assert scan_apps(apps) == []


def test_forbidden_markers_detect_cheat_paths() -> None:
    assert path_is_forbidden("/v1/actual-root-cause")
    assert path_is_forbidden("/internal/ground_truth")
    assert "actual-root-cause" in FORBIDDEN_PATH_MARKERS


def test_auth_validate_demo_user() -> None:
    client = TestClient(_app("auth"))
    res = client.post(
        "/v1/sessions/validate",
        json={"user_id": "user_demo", "token": "tok_demo_user"},
    )
    assert res.status_code == 200
    assert res.json()["valid"] is True


def test_inventory_reserve_and_payment_charge() -> None:
    inv = TestClient(_app("inventory"))
    pay = TestClient(_app("payment"))
    reserved = inv.post("/v1/reservations", json={"sku": "SKU-WIDGET", "quantity": 1})
    assert reserved.status_code == 200
    charged = pay.post(
        "/v1/charges",
        json={
            "amount_cents": 2500,
            "currency": "USD",
            "card_last4": "4242",
            "order_ref": "ord-test",
        },
    )
    assert charged.status_code == 200
    assert charged.json()["status"] == "captured"


def test_checkout_creates_order() -> None:
    client = TestClient(_app("checkout"))
    res = client.post(
        "/v1/orders",
        json={
            "user_id": "user_demo",
            "sku": "SKU-WIDGET",
            "quantity": 1,
            "reservation_id": "res_test",
            "charge_id": "ch_test",
            "amount_cents": 2500,
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "confirmed"
    order_id = res.json()["order_id"]
    got = client.get(f"/v1/orders/{order_id}")
    assert got.status_code == 200
