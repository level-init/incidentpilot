"""Shared health / readiness helpers for sim services (E4 baseline gate)."""

from __future__ import annotations

from typing import Any, Literal

HealthStatus = Literal["ok", "degraded", "error"]


def health_payload(
    service: str,
    *,
    status: HealthStatus = "ok",
    **extra: Any,
) -> dict[str, Any]:
    """Standard liveness body: always includes status + service."""
    body: dict[str, Any] = {"status": status, "service": service}
    body.update(extra)
    return body
