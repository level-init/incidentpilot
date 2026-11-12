"""Fault inject / reset via sim control API (E5)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx


def _ensure_sim_path() -> None:
    root = Path(__file__).resolve().parents[2]
    sim = str(root / "simulation")
    if sim not in sys.path:
        sys.path.insert(0, sim)


def activate_injector(injector_id: str) -> dict[str, Any]:
    _ensure_sim_path()
    from common.faults import control_base_url  # type: ignore[import-untyped]
    from faults.catalog import CATALOG, activation_plan  # type: ignore[import-untyped]

    if injector_id not in CATALOG:
        raise KeyError(f"unknown injector: {injector_id}")

    plan = activation_plan(injector_id)
    results = []
    with httpx.Client(timeout=5.0) as client:
        for step in plan:
            service = step["service"]
            url = (
                f"{control_base_url(service).rstrip('/')}"
                f"/v1/injectors/{injector_id}/activate"
            )
            res = client.post(url, json={})
            res.raise_for_status()
            results.append(res.json())
    return {"injector": injector_id, "activated": results}


def reset_injectors() -> dict[str, Any]:
    _ensure_sim_path()
    from common.faults import control_base_url  # type: ignore[import-untyped]

    targets = (
        "gateway",
        "auth",
        "checkout",
        "payment",
        "inventory",
        "notification",
    )
    results = []
    with httpx.Client(timeout=5.0) as client:
        for service in targets:
            url = f"{control_base_url(service).rstrip('/')}/v1/injectors/reset"
            try:
                res = client.post(url)
                res.raise_for_status()
                results.append(res.json())
            except httpx.HTTPError as exc:
                results.append({"service": service, "error": str(exc)})
    return {"reset": results}
