"""Shared metrics, structured JSON logs, and OTel tracing for sim services (E2)."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

# --- Prometheus (latency + errors) -------------------------------------------------

REQUEST_LATENCY = Histogram(
    "sim_http_request_duration_seconds",
    "HTTP request latency seconds",
    labelnames=("service", "method", "handler", "status"),
)
REQUEST_ERRORS = Counter(
    "sim_http_request_errors_total",
    "HTTP requests with status >= 500 or handled 4xx business failures",
    labelnames=("service", "method", "handler", "status"),
)
REQUESTS = Counter(
    "sim_http_requests_total",
    "HTTP requests",
    labelnames=("service", "method", "handler", "status"),
)

_httpx_instrumented = False
_logging_configured_for: set[str] = set()


class StructuredJsonFormatter(logging.Formatter):
    """JSON logs with required fields: timestamp, level, service, message, trace/span."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "service": self._service,
            "message": record.getMessage(),
            "logger": record.name,
        }
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            payload["trace_id"] = format(ctx.trace_id, "032x")
            payload["span_id"] = format(ctx.span_id, "016x")
        for key in ("method", "path", "status_code", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_structured_logging(service: str, *, level: str | None = None) -> None:
    if service in _logging_configured_for:
        return
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredJsonFormatter(service))
    root.addHandler(handler)
    root.setLevel((level or os.environ.get("LOG_LEVEL", "INFO")).upper())
    _logging_configured_for.add(service)


def _setup_tracer_provider(
    service: str,
    *,
    tracer_provider: TracerProvider | None = None,
) -> TracerProvider:
    if tracer_provider is not None:
        trace.set_tracer_provider(tracer_provider)
        return tracer_provider

    existing = trace.get_tracer_provider()
    # Reuse if SDK provider already installed (tests / multi-app process).
    if isinstance(existing, TracerProvider):
        return existing

    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME", service),
            "service.namespace": "incidentpilot-simulation",
        }
    )
    provider = TracerProvider(resource=resource)

    # Prefer std OTEL_* env (E3 Tempo). Constructor reads endpoint from the environment.
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
    ):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    elif os.environ.get("OTEL_CONSOLE_EXPORT", "").lower() in {"1", "true", "yes"}:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    return provider


class _MetricsAndLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, service: str) -> None:
        super().__init__(app)
        self._service = service
        self._log = logging.getLogger(f"sim.{service}.http")

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        start = time.perf_counter()
        handler = request.url.path
        method = request.method
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            labels = {
                "service": self._service,
                "method": method,
                "handler": handler,
                "status": str(status_code),
            }
            REQUEST_LATENCY.labels(**labels).observe(duration)
            REQUESTS.labels(**labels).inc()
            if status_code >= 400:
                REQUEST_ERRORS.labels(**labels).inc()
            self._log.info(
                "request completed",
                extra={
                    "method": method,
                    "path": handler,
                    "status_code": status_code,
                    "duration_ms": round(duration * 1000, 3),
                },
            )


def instrument_app(
    app: FastAPI,
    service: str,
    *,
    tracer_provider: TracerProvider | None = None,
) -> None:
    """Attach Prometheus /metrics, structured logs, and OTel FastAPI (+ httpx) instrumentation."""
    global _httpx_instrumented

    configure_structured_logging(service)
    _setup_tracer_provider(service, tracer_provider=tracer_provider)

    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument()
        _httpx_instrumented = True

    # Avoid double-instrumenting the same app object in tests.
    if not getattr(app.state, "_sim_otel_instrumented", False):
        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,metrics")
        app.state._sim_otel_instrumented = True

    if not getattr(app.state, "_sim_metrics_middleware", False):
        app.add_middleware(_MetricsAndLogMiddleware, service=service)
        app.state._sim_metrics_middleware = True

    if not getattr(app.state, "_sim_metrics_route", False):

        @app.get("/metrics")
        def metrics() -> Response:
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

        app.state._sim_metrics_route = True


def get_tracer(service: str) -> trace.Tracer:
    return trace.get_tracer(f"incidentpilot.sim.{service}")
