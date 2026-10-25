"""Baseline traffic profiles against the sim gateway / services (E4)."""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import httpx

# Default local ports (host) — overridden by SIM_*_URL env vars in Compose.
_DEFAULTS = {
    "gateway": "http://127.0.0.1:8100",
    "auth": "http://127.0.0.1:8101",
    "checkout": "http://127.0.0.1:8102",
    "payment": "http://127.0.0.1:8103",
    "inventory": "http://127.0.0.1:8104",
    "notification": "http://127.0.0.1:8105",
}

SERVICES = tuple(_DEFAULTS.keys())


def service_url(name: str) -> str:
    env_key = f"SIM_{name.upper()}_URL"
    if name == "gateway":
        return os.environ.get("SIM_GATEWAY_URL") or os.environ.get(env_key, _DEFAULTS[name])
    return os.environ.get(env_key, _DEFAULTS[name])


@dataclass
class BaselineResult:
    duration_s: float
    requests: int = 0
    successes: int = 0
    failures: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    error_samples: list[str] = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        if self.requests == 0:
            return 0.0
        return self.failures / self.requests

    def ok(self, *, max_error_rate: float = 0.05) -> bool:
        return self.requests > 0 and self.error_rate <= max_error_rate


def check_healthz(client: httpx.Client, base: str, *, service: str) -> dict[str, Any]:
    res = client.get(urljoin(base.rstrip("/") + "/", "healthz"))
    res.raise_for_status()
    body = res.json()
    if body.get("service") != service:
        raise AssertionError(f"healthz service mismatch: {body}")
    if body.get("status") != "ok":
        raise AssertionError(f"healthz not ok: {body}")
    return body


def check_all_healthz(client: httpx.Client | None = None) -> dict[str, dict[str, Any]]:
    own = client is None
    client = client or httpx.Client(timeout=5.0)
    try:
        out: dict[str, dict[str, Any]] = {}
        for name in SERVICES:
            out[name] = check_healthz(client, service_url(name), service=name)
        # Gateway readiness aggregates upstreams.
        ready = client.get(urljoin(service_url("gateway").rstrip("/") + "/", "readyz"))
        ready.raise_for_status()
        ready_body = ready.json()
        if ready_body.get("status") != "ok":
            raise AssertionError(f"readyz not ok: {ready_body}")
        out["gateway_readyz"] = ready_body
        return out
    finally:
        if own:
            client.close()


def _do_health(client: httpx.Client) -> None:
    name = random.choice(SERVICES)
    check_healthz(client, service_url(name), service=name)


def _do_auth_validate(client: httpx.Client) -> None:
    res = client.post(
        urljoin(service_url("auth").rstrip("/") + "/", "v1/sessions/validate"),
        json={"user_id": "user_demo", "token": "tok_demo_user"},
    )
    res.raise_for_status()


def _do_stock_get(client: httpx.Client) -> None:
    sku = random.choice(["SKU-WIDGET", "SKU-GADGET"])
    res = client.get(urljoin(service_url("inventory").rstrip("/") + "/", f"v1/stock/{sku}"))
    res.raise_for_status()


def _do_checkout(client: httpx.Client) -> None:
    sku = random.choice(["SKU-WIDGET", "SKU-GADGET"])
    res = client.post(
        urljoin(service_url("gateway").rstrip("/") + "/", "v1/checkout"),
        json={
            "user_id": "user_demo",
            "token": "tok_demo_user",
            "sku": sku,
            "quantity": 1,
            "card_last4": "4242",
        },
    )
    res.raise_for_status()
    body = res.json()
    if body.get("status") != "confirmed":
        raise AssertionError(f"checkout not confirmed: {body}")


# Weighted baseline mix: mostly probes / reads so stock lasts; some checkouts.
_BASELINE_WEIGHTS: list[tuple[str, float, Callable[[httpx.Client], None]]] = [
    ("healthz", 0.35, _do_health),
    ("auth_validate", 0.20, _do_auth_validate),
    ("stock_get", 0.25, _do_stock_get),
    ("checkout", 0.20, _do_checkout),
]


def _pick_action() -> tuple[str, Callable[[httpx.Client], None]]:
    roll = random.random()
    acc = 0.0
    for kind, weight, fn in _BASELINE_WEIGHTS:
        acc += weight
        if roll <= acc:
            return kind, fn
    kind, _, fn = _BASELINE_WEIGHTS[-1]
    return kind, fn


def run_baseline(
    *,
    duration_s: float = 60.0,
    rps: float = 1.0,
    max_error_rate: float = 0.05,
    concurrency: int = 4,
    seed: int | None = 42,
    require_health_gate: bool = True,
    client: httpx.Client | None = None,
) -> BaselineResult:
    """Drive baseline load for ``duration_s`` at ~``rps`` requests/second.

    ``duration_s <= 0`` runs until interrupted (Compose long-running generator).
    """
    if seed is not None:
        random.seed(seed)

    own_client = client is None
    client = client or httpx.Client(timeout=10.0)
    result = BaselineResult(duration_s=duration_s)

    try:
        if require_health_gate:
            check_all_healthz(client)

        interval = 1.0 / rps if rps > 0 else 1.0
        deadline = None if duration_s <= 0 else time.monotonic() + duration_s
        workers = max(1, concurrency)

        def one() -> tuple[str, str | None]:
            kind, fn = _pick_action()
            try:
                fn(client)
                return kind, None
            except Exception as exc:
                return kind, f"{kind}: {exc}"

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                while deadline is None or time.monotonic() < deadline:
                    tick_start = time.monotonic()
                    # Issue ~rps work each second (batch of workers capped).
                    batch = max(1, int(round(rps))) if rps >= 1 else 1
                    futures = [pool.submit(one) for _ in range(batch)]
                    for fut in as_completed(futures):
                        kind, err = fut.result()
                        result.requests += 1
                        result.by_kind[kind] = result.by_kind.get(kind, 0) + 1
                        if err is None:
                            result.successes += 1
                        else:
                            result.failures += 1
                            if len(result.error_samples) < 10:
                                result.error_samples.append(err)
                    # Pace to ~1s per tick when rps>=1; for fractional rps sleep interval.
                    elapsed = time.monotonic() - tick_start
                    sleep_for = (interval if rps < 1 else 1.0) - elapsed
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                    if deadline is not None and time.monotonic() >= deadline:
                        break
        except KeyboardInterrupt:
            pass

        # End-of-run health gate: still healthy after load (finite runs only).
        if require_health_gate and duration_s > 0:
            check_all_healthz(client)

        if duration_s > 0 and not result.ok(max_error_rate=max_error_rate):
            raise RuntimeError(
                f"baseline failed: error_rate={result.error_rate:.3f} "
                f"(max={max_error_rate}) requests={result.requests} "
                f"samples={result.error_samples}"
            )
        return result
    finally:
        if own_client:
            client.close()
