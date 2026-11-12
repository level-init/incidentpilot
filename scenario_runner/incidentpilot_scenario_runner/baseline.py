"""Baseline gate before fault injection (N1 / E4 contract)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BaselineGateResult:
    ok: bool
    payload: dict[str, Any]
    detail: str = ""


def run_baseline_gate() -> BaselineGateResult:
    """Probe sim /healthz + gateway /readyz. Does not inject faults."""
    # Import from simulation package (PYTHONPATH includes simulation/).
    try:
        from traffic.generator import check_all_healthz
    except ImportError as exc:
        return BaselineGateResult(
            ok=False,
            payload={"error": "import_failed", "detail": str(exc)},
            detail=f"baseline import failed: {exc}",
        )

    try:
        bodies = check_all_healthz()
        return BaselineGateResult(ok=True, payload=bodies, detail="baseline ok")
    except Exception as exc:  # noqa: BLE001 — gate must capture dirty env
        return BaselineGateResult(
            ok=False,
            payload={"error": type(exc).__name__, "detail": str(exc)},
            detail=str(exc),
        )


def ensure_simulation_on_path(root_simulation: str) -> None:
    if root_simulation not in sys.path:
        sys.path.insert(0, root_simulation)
