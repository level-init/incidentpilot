"""E4: baseline health/ready contract + traffic generator."""

from __future__ import annotations

import importlib
import sys
import threading
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "simulation"
if str(SIM) not in sys.path:
    sys.path.insert(0, str(SIM))

SERVICES = ("auth", "checkout", "payment", "inventory", "notification", "gateway")


def _app(name: str):
    return importlib.import_module(f"{name}.app").app


def _ensure_tracer() -> None:
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(
            TracerProvider(resource=Resource.create({"service.name": "sim-test"}))
        )


@pytest.mark.parametrize("name", SERVICES)
def test_healthz_contract(name: str) -> None:
    _ensure_tracer()
    client = TestClient(_app(name))
    res = client.get("/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == name


def test_inventory_healthz_includes_stock() -> None:
    _ensure_tracer()
    body = TestClient(_app("inventory")).get("/healthz").json()
    assert "stock_total" in body
    assert body["stock_total"] > 0


def test_gateway_readyz_requires_upstreams(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_tracer()
    # Point upstreams at a closed port so readiness fails.
    monkeypatch.setenv("SIM_AUTH_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("SIM_CHECKOUT_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("SIM_PAYMENT_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("SIM_INVENTORY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("SIM_NOTIFICATION_URL", "http://127.0.0.1:1")
    # Re-import gateway so URL helpers see env (they read at call time — no reload needed).
    client = TestClient(_app("gateway"))
    res = client.get("/readyz")
    assert res.status_code == 503


def test_run_baseline_against_local_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spin all six apps + short baseline load; health stays ok."""
    import socket
    import time
    from collections.abc import Iterator
    from contextlib import contextmanager

    from traffic.generator import check_all_healthz, run_baseline

    _ensure_tracer()
    apps = {name: _app(name) for name in SERVICES}

    def free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    @contextmanager
    def serve(app: object, port: int) -> Iterator[None]:
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

    ports = {name: free_port() for name in SERVICES}
    monkeypatch.setenv("SIM_GATEWAY_URL", f"http://127.0.0.1:{ports['gateway']}")
    monkeypatch.setenv("SIM_AUTH_URL", f"http://127.0.0.1:{ports['auth']}")
    monkeypatch.setenv("SIM_CHECKOUT_URL", f"http://127.0.0.1:{ports['checkout']}")
    monkeypatch.setenv("SIM_PAYMENT_URL", f"http://127.0.0.1:{ports['payment']}")
    monkeypatch.setenv("SIM_INVENTORY_URL", f"http://127.0.0.1:{ports['inventory']}")
    monkeypatch.setenv("SIM_NOTIFICATION_URL", f"http://127.0.0.1:{ports['notification']}")

    with (
        serve(apps["auth"], ports["auth"]),
        serve(apps["checkout"], ports["checkout"]),
        serve(apps["payment"], ports["payment"]),
        serve(apps["inventory"], ports["inventory"]),
        serve(apps["notification"], ports["notification"]),
        serve(apps["gateway"], ports["gateway"]),
    ):
        gate = check_all_healthz()
        assert gate["gateway"]["status"] == "ok"
        assert gate["gateway_readyz"]["status"] == "ok"

        result = run_baseline(
            duration_s=3.0,
            rps=2.0,
            max_error_rate=0.05,
            concurrency=2,
            seed=7,
        )
        assert result.ok()
        assert result.requests >= 3
        # Still healthy after load.
        check_all_healthz()


def test_baseline_doc_exists() -> None:
    text = (ROOT / "docs" / "sim-baseline.md").read_text()
    assert "/healthz" in text
    assert "/readyz" in text
    assert "error_rate" in text
