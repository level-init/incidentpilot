"""In-process fault injection for sim services (E5).

Injectors change runtime behavior only. They must not emit GroundTruth /
answer-key labels on metrics or alerts — symptoms appear as normal latency,
errors, memory, and queue depth.

State is keyed by service name so multiple apps in one process (tests) isolate.
"""

from __future__ import annotations

import asyncio
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from prometheus_client import Gauge
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Natural ops signal — depth only, no root-cause / scenario-class labels.
QUEUE_DEPTH = Gauge(
    "sim_notification_queue_depth",
    "Notification backlog depth (ops signal)",
    labelnames=("service",),
)

_SKIP_PREFIXES = ("/healthz", "/readyz", "/metrics", "/v1/injectors", "/docs", "/openapi")


@dataclass
class ActiveFault:
    injector: str
    effects: dict[str, Any] = field(default_factory=dict)


@dataclass
class _ServiceState:
    active: ActiveFault | None = None
    leak_chunks: list[bytearray] = field(default_factory=list)
    inflight: int = 0
    queue_depth: int = 0


_lock = threading.RLock()
_by_service: dict[str, _ServiceState] = {}


def _state(service: str) -> _ServiceState:
    with _lock:
        if service not in _by_service:
            _by_service[service] = _ServiceState()
        return _by_service[service]


def get_active(service: str) -> ActiveFault | None:
    with _lock:
        return _state(service).active


def activate(service: str, injector: str, effects: dict[str, Any]) -> ActiveFault:
    with _lock:
        fault = ActiveFault(injector=injector, effects=dict(effects))
        _state(service).active = fault
        return fault


def reset(service: str | None = None) -> None:
    with _lock:
        services = [service] if service else list(_by_service.keys())
        if not services and service:
            _by_service[service] = _ServiceState()
            services = [service]
        for name in list(_by_service.keys()) if service is None else services:
            st = _state(name)
            st.active = None
            st.leak_chunks.clear()
            st.inflight = 0
            st.queue_depth = 0
            try:
                QUEUE_DEPTH.labels(service=name).set(0)
            except Exception:
                pass
        if service is None:
            _by_service.clear()


def leak_chunk_count(service: str) -> int:
    with _lock:
        return len(_state(service).leak_chunks)


def _effects(service: str) -> dict[str, Any]:
    with _lock:
        active = _state(service).active
        return dict(active.effects) if active else {}


def _apply_cpu_burn(ms: float) -> None:
    if ms <= 0:
        return
    end = time.perf_counter() + (ms / 1000.0)
    x = 0
    while time.perf_counter() < end:
        x = (x + 1) % 10_000_019
    _ = x


def _apply_alloc(service: str, mb: float) -> None:
    if mb <= 0:
        return
    chunk = bytearray(int(mb * 1024 * 1024))
    with _lock:
        _state(service).leak_chunks.append(chunk)


def _bump_queue(service: str, delta: int) -> None:
    with _lock:
        st = _state(service)
        st.queue_depth = max(0, st.queue_depth + delta)
        QUEUE_DEPTH.labels(service=service).set(st.queue_depth)


class FaultMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, service: str) -> None:
        super().__init__(app)
        self._service = service

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in _SKIP_PREFIXES):
            return await call_next(request)

        service = self._service
        effects = _effects(service)
        if not effects:
            return await call_next(request)

        cpu_ms = float(effects.get("cpu_burn_ms", 0) or 0)
        if cpu_ms:
            await asyncio.to_thread(_apply_cpu_burn, cpu_ms)

        alloc_mb = float(effects.get("alloc_mb", 0) or 0)
        if alloc_mb:
            await asyncio.to_thread(_apply_alloc, service, alloc_mb)

        latency_ms = float(effects.get("latency_ms", 0) or 0)
        if latency_ms:
            await asyncio.sleep(latency_ms / 1000.0)

        queue_delay_ms = float(effects.get("queue_delay_ms", 0) or 0)
        if queue_delay_ms:
            _bump_queue(service, 1)
            await asyncio.sleep(queue_delay_ms / 1000.0)
            _bump_queue(service, -1)

        error_rate = float(effects.get("error_rate", 0) or 0)
        error_status = int(effects.get("error_status", 500) or 500)
        if error_rate > 0 and random.random() < error_rate:
            detail = str(effects.get("error_detail", "injected fault"))
            return JSONResponse({"detail": detail}, status_code=error_status)

        max_inflight = effects.get("max_inflight")
        if max_inflight is not None:
            limit = int(max_inflight)
            with _lock:
                st = _state(service)
                if st.inflight >= limit:
                    return JSONResponse(
                        {"detail": "resource unavailable"},
                        status_code=503,
                    )
                st.inflight += 1
            try:
                return await call_next(request)
            finally:
                with _lock:
                    _state(service).inflight -= 1

        return await call_next(request)


def build_injector_router(service: str) -> APIRouter:
    router = APIRouter(prefix="/v1/injectors", tags=["injectors"])

    @router.get("")
    def list_injectors() -> dict[str, Any]:
        from faults.catalog import injectors_for_service

        active = get_active(service)
        return {
            "service": service,
            "available": sorted(injectors_for_service(service)),
            "active": None
            if active is None
            else {"injector": active.injector, "effects": active.effects},
        }

    @router.post("/{injector_id}/activate")
    def activate_injector(injector_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        from faults.catalog import resolve_effects

        try:
            effects = resolve_effects(injector_id, service, overrides=body or {})
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        fault = activate(service, injector_id, effects)
        return {"service": service, "injector": fault.injector, "effects": fault.effects}

    @router.post("/reset")
    def reset_injectors() -> dict[str, str]:
        reset(service)
        return {"status": "ok", "service": service}

    return router


def install_faults(app: FastAPI, service: str) -> None:
    """Attach fault middleware + injector control routes to a sim app."""
    if getattr(app.state, "_sim_faults_installed", False):
        return
    app.add_middleware(FaultMiddleware, service=service)
    app.include_router(build_injector_router(service))
    app.state.sim_service = service
    app.state._sim_faults_installed = True


def control_base_url(service: str) -> str:
    defaults = {
        "gateway": 8100,
        "auth": 8101,
        "checkout": 8102,
        "payment": 8103,
        "inventory": 8104,
        "notification": 8105,
    }
    if service == "gateway":
        return os.environ.get("SIM_GATEWAY_URL", f"http://127.0.0.1:{defaults['gateway']}")
    return os.environ.get(
        f"SIM_{service.upper()}_URL",
        f"http://127.0.0.1:{defaults[service]}",
    )
