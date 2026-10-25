"""E2: sim metrics, structured logs, and gateway→checkout→payment traces."""

from __future__ import annotations

import importlib
import json
import logging
import socket
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "simulation"
if str(SIM) not in sys.path:
    sys.path.insert(0, str(SIM))

SERVICES = ("auth", "checkout", "payment", "inventory", "notification", "gateway")


def _app(name: str):
    return importlib.import_module(f"{name}.app").app


def _attach_in_memory_exporter() -> InMemorySpanExporter:
    """Attach an in-memory exporter to the process TracerProvider (OTel forbids replace)."""
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": "sim-test",
                    "service.namespace": "incidentpilot-simulation",
                }
            )
        )
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.mark.parametrize("name", SERVICES)
def test_metrics_endpoint(name: str) -> None:
    client = TestClient(_app(name))
    client.get("/healthz")
    res = client.get("/metrics")
    assert res.status_code == 200
    body = res.text
    assert "sim_http_requests_total" in body
    assert "sim_http_request_duration_seconds" in body
    assert f'service="{name}"' in body


def test_error_metrics_visible_on_payment_decline() -> None:
    client = TestClient(_app("payment"))
    declined = client.post(
        "/v1/charges",
        json={
            "amount_cents": 100,
            "currency": "USD",
            "card_last4": "0000",
            "order_ref": "ord-decline",
        },
    )
    assert declined.status_code == 402
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "sim_http_request_errors_total" in metrics.text
    assert 'status="402"' in metrics.text


def test_structured_log_includes_required_fields() -> None:
    from common.observability import StructuredJsonFormatter, configure_structured_logging

    configure_structured_logging("payment")
    formatter = StructuredJsonFormatter("payment")
    record = logging.LogRecord(
        name="sim.payment.http",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.method = "POST"
    record.path = "/v1/charges"
    record.status_code = 200
    record.duration_ms = 1.5
    payload = json.loads(formatter.format(record))
    assert payload["service"] == "payment"
    assert payload["level"] == "INFO"
    assert payload["message"] == "request completed"
    assert "timestamp" in payload


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _serve(app: object, port: int) -> Iterator[None]:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        raise RuntimeError(f"server on {port} did not start")
    try:
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_traces_span_gateway_checkout_payment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure apps are imported/instrumented before attaching the exporter.
    apps = {name: _app(name) for name in SERVICES}
    exporter = _attach_in_memory_exporter()
    exporter.clear()

    ports = {name: _free_port() for name in SERVICES}
    monkeypatch.setenv("SIM_AUTH_URL", f"http://127.0.0.1:{ports['auth']}")
    monkeypatch.setenv("SIM_CHECKOUT_URL", f"http://127.0.0.1:{ports['checkout']}")
    monkeypatch.setenv("SIM_PAYMENT_URL", f"http://127.0.0.1:{ports['payment']}")
    monkeypatch.setenv("SIM_INVENTORY_URL", f"http://127.0.0.1:{ports['inventory']}")
    monkeypatch.setenv("SIM_NOTIFICATION_URL", f"http://127.0.0.1:{ports['notification']}")

    with (
        _serve(apps["auth"], ports["auth"]),
        _serve(apps["checkout"], ports["checkout"]),
        _serve(apps["payment"], ports["payment"]),
        _serve(apps["inventory"], ports["inventory"]),
        _serve(apps["notification"], ports["notification"]),
        _serve(apps["gateway"], ports["gateway"]),
    ):
        res = httpx.post(
            f"http://127.0.0.1:{ports['gateway']}/v1/checkout",
            json={
                "user_id": "user_demo",
                "token": "tok_demo_user",
                "sku": "SKU-WIDGET",
                "quantity": 1,
                "card_last4": "4242",
            },
            timeout=10.0,
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "confirmed"

    spans = exporter.get_finished_spans()
    assert spans, "expected OTel spans from instrumented sim stack"

    span_names = {s.name for s in spans}
    assert any("/v1/checkout" in n for n in span_names)
    assert any("/v1/orders" in n for n in span_names)
    assert any("/v1/charges" in n for n in span_names)

    checkout_related = [
        s
        for s in spans
        if "/v1/checkout" in s.name or "/v1/orders" in s.name or "/v1/charges" in s.name
    ]
    primary = format(checkout_related[0].context.trace_id, "032x")
    covered = {
        s.name
        for s in spans
        if format(s.context.trace_id, "032x") == primary
        and ("/v1/checkout" in s.name or "/v1/orders" in s.name or "/v1/charges" in s.name)
    }
    assert any("/v1/checkout" in n for n in covered)
    assert any("/v1/orders" in n for n in covered)
    assert any("/v1/charges" in n for n in covered)
