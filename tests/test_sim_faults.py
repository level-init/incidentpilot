"""E5: eight fault injectors produce natural degradation without GT leakage."""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "simulation"
if str(SIM) not in sys.path:
    sys.path.insert(0, str(SIM))

from common.contract import assert_no_forbidden_routes, scan_apps  # noqa: E402
from common.faults import leak_chunk_count  # noqa: E402
from common.faults import reset as reset_faults  # noqa: E402
from faults.catalog import CATALOG  # noqa: E402

SERVICES = ("auth", "checkout", "payment", "inventory", "notification", "gateway")

FORBIDDEN_METRIC_MARKERS = (
    "ground_truth",
    "ground-truth",
    "answer_key",
    "answer-key",
    "actual_root_cause",
    "actual-root-cause",
    "root_cause_oracle",
)


def _ensure_tracer() -> None:
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(
            TracerProvider(resource=Resource.create({"service.name": "sim-test"}))
        )


def _app(name: str):
    _ensure_tracer()
    return importlib.import_module(f"{name}.app").app


def _client(name: str) -> TestClient:
    return TestClient(_app(name))


def _charge(client: TestClient) -> int:
    return client.post(
        "/v1/charges",
        json={
            "amount_cents": 100,
            "currency": "USD",
            "card_last4": "4242",
            "order_ref": "fault-test",
        },
    ).status_code


@pytest.fixture(autouse=True)
def _clean_faults() -> None:
    reset_faults()
    yield
    reset_faults()


def test_catalog_has_eight_injectors() -> None:
    assert set(CATALOG) == {
        "bad_deploy",
        "dependency_timeout",
        "db_exhaustion",
        "memory_leak",
        "cpu_exhaustion",
        "queue_backlog",
        "bad_config",
        "cascading_failure",
    }


@pytest.mark.parametrize("name", SERVICES)
def test_injector_routes_not_forbidden(name: str) -> None:
    assert_no_forbidden_routes(_app(name), service=name)
    assert scan_apps([(name, _app(name))]) == []


def test_metrics_have_no_answer_key_markers() -> None:
    client = _client("payment")
    client.post("/v1/injectors/bad_deploy/activate", json={})
    text = client.get("/metrics").text.lower()
    for marker in FORBIDDEN_METRIC_MARKERS:
        assert marker not in text


def test_bad_deploy_raises_payment_errors() -> None:
    client = _client("payment")
    client.post("/v1/injectors/bad_deploy/activate", json={})
    codes = [_charge(client) for _ in range(30)]
    assert sum(1 for c in codes if c >= 500) >= 15


def test_dependency_timeout_adds_latency() -> None:
    client = _client("payment")
    client.post(
        "/v1/injectors/dependency_timeout/activate",
        json={"latency_ms": 120},
    )
    start = time.perf_counter()
    _charge(client)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms >= 100


def test_db_exhaustion_blocks_inventory() -> None:
    client = _client("inventory")
    client.post("/v1/injectors/db_exhaustion/activate", json={})
    res = client.post("/v1/reservations", json={"sku": "SKU-WIDGET", "quantity": 1})
    assert res.status_code == 503


def test_memory_leak_allocates() -> None:
    client = _client("checkout")
    client.post("/v1/injectors/memory_leak/activate", json={"alloc_mb": 1})
    before = leak_chunk_count("checkout")
    client.post(
        "/v1/orders",
        json={
            "user_id": "user_demo",
            "sku": "SKU-WIDGET",
            "quantity": 1,
            "reservation_id": "res_x",
            "charge_id": "ch_x",
            "amount_cents": 2500,
        },
    )
    assert leak_chunk_count("checkout") > before


def test_cpu_exhaustion_slows_checkout() -> None:
    client = _client("checkout")
    client.post(
        "/v1/injectors/cpu_exhaustion/activate",
        json={"cpu_burn_ms": 80},
    )
    start = time.perf_counter()
    client.post(
        "/v1/orders",
        json={
            "user_id": "user_demo",
            "sku": "SKU-WIDGET",
            "quantity": 1,
            "reservation_id": "res_y",
            "charge_id": "ch_y",
            "amount_cents": 2500,
        },
    )
    assert (time.perf_counter() - start) * 1000 >= 60


def test_queue_backlog_delays_notification_and_exposes_depth_metric() -> None:
    client = _client("notification")
    client.post(
        "/v1/injectors/queue_backlog/activate",
        json={"queue_delay_ms": 80, "latency_ms": 20},
    )
    start = time.perf_counter()
    res = client.post(
        "/v1/messages",
        json={
            "user_id": "user_demo",
            "channel": "email",
            "template": "order_confirmed",
            "order_id": "ord_test",
        },
    )
    assert res.status_code == 200
    assert (time.perf_counter() - start) * 1000 >= 70
    metrics = client.get("/metrics").text
    assert "sim_notification_queue_depth" in metrics
    for marker in FORBIDDEN_METRIC_MARKERS:
        assert marker not in metrics.lower()


def test_bad_config_rejects_auth() -> None:
    client = _client("auth")
    client.post("/v1/injectors/bad_config/activate", json={})
    res = client.post(
        "/v1/sessions/validate",
        json={"user_id": "user_demo", "token": "tok_demo_user"},
    )
    assert res.status_code == 401


def test_cascading_failure_hurts_payment_and_inventory() -> None:
    pay = _client("payment")
    inv = _client("inventory")
    # Override catalog latency so the unit test stays fast; CI still proves errors.
    pay.post(
        "/v1/injectors/cascading_failure/activate",
        json={"latency_ms": 0, "error_rate": 0.6, "error_status": 500},
    )
    inv.post(
        "/v1/injectors/cascading_failure/activate",
        json={"error_rate": 0.6, "error_status": 503},
    )
    pay_codes = [_charge(pay) for _ in range(20)]
    inv_codes = [
        inv.post("/v1/reservations", json={"sku": "SKU-GADGET", "quantity": 1}).status_code
        for _ in range(20)
    ]
    assert sum(1 for c in pay_codes if c >= 500) >= 5
    assert sum(1 for c in inv_codes if c >= 500) >= 5


def test_reset_clears_fault() -> None:
    client = _client("payment")
    client.post("/v1/injectors/bad_deploy/activate", json={})
    client.post("/v1/injectors/reset")
    codes = [_charge(client) for _ in range(10)]
    assert all(c == 200 for c in codes)


def test_forbidden_override_fields_rejected() -> None:
    client = _client("payment")
    res = client.post(
        "/v1/injectors/bad_deploy/activate",
        json={"root_cause": "payment"},
    )
    assert res.status_code == 404
