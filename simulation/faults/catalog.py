"""Eight scenario-class injectors → target service + effects (E5).

Injector ids match product scenario classes so the scenario runner can activate
them. Effects are mechanism-only (latency, errors, CPU, memory, queue). No
GroundTruth / answer-key fields are exposed on metrics.
"""

from __future__ import annotations

from typing import Any

# Canonical injector id → one or more (service, default effects) activations.
CATALOG: dict[str, list[dict[str, Any]]] = {
    "bad_deploy": [
        {
            "service": "payment",
            "effects": {
                "error_rate": 0.85,
                "error_status": 500,
                "error_detail": "upstream processing error",
            },
        }
    ],
    "dependency_timeout": [
        {
            "service": "payment",
            "effects": {
                # Exceeds gateway httpx timeout (10s) → gateway 503 / latency.
                "latency_ms": 12_000,
            },
        }
    ],
    "db_exhaustion": [
        {
            "service": "inventory",
            "effects": {
                "max_inflight": 0,
                "error_rate": 1.0,
                "error_status": 503,
                "error_detail": "resource unavailable",
            },
        }
    ],
    "memory_leak": [
        {
            "service": "checkout",
            "effects": {
                "alloc_mb": 8,
            },
        }
    ],
    "cpu_exhaustion": [
        {
            "service": "checkout",
            "effects": {
                "cpu_burn_ms": 400,
            },
        }
    ],
    "queue_backlog": [
        {
            "service": "notification",
            "effects": {
                "queue_delay_ms": 1500,
                "latency_ms": 500,
            },
        }
    ],
    "bad_config": [
        {
            "service": "auth",
            "effects": {
                "error_rate": 1.0,
                "error_status": 401,
                "error_detail": "invalid session",
            },
        }
    ],
    "cascading_failure": [
        {
            "service": "payment",
            "effects": {
                "latency_ms": 2500,
                "error_rate": 0.4,
                "error_status": 500,
                "error_detail": "upstream processing error",
            },
        },
        {
            "service": "inventory",
            "effects": {
                "error_rate": 0.5,
                "error_status": 503,
                "error_detail": "resource unavailable",
            },
        },
    ],
}


def injectors_for_service(service: str) -> list[str]:
    found: list[str] = []
    for injector_id, steps in CATALOG.items():
        if any(step["service"] == service for step in steps):
            found.append(injector_id)
    return found


def resolve_effects(
    injector_id: str,
    service: str,
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if injector_id not in CATALOG:
        raise KeyError(f"unknown injector: {injector_id}")
    matches = [s for s in CATALOG[injector_id] if s["service"] == service]
    if not matches:
        raise KeyError(f"injector {injector_id} not hosted on service {service}")
    effects = dict(matches[0]["effects"])
    if overrides:
        # Allow param tweaks only — never attach answer-key fields.
        forbidden = {"root_cause", "ground_truth", "answer_key", "actual_root_cause"}
        bad = forbidden.intersection(overrides)
        if bad:
            raise KeyError(f"forbidden override fields: {sorted(bad)}")
        effects.update(overrides)
    return effects


def activation_plan(injector_id: str) -> list[dict[str, Any]]:
    if injector_id not in CATALOG:
        raise KeyError(f"unknown injector: {injector_id}")
    return list(CATALOG[injector_id])
