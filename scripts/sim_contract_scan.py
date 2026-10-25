#!/usr/bin/env python3
"""Fail if simulation services expose GroundTruth / root-cause cheat routes (E1)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "simulation"
sys.path.insert(0, str(SIM))

from common.contract import scan_apps  # noqa: E402


def _load_apps() -> list[tuple[str, object]]:
    services = ("auth", "checkout", "payment", "inventory", "notification", "gateway")
    apps: list[tuple[str, object]] = []
    for name in services:
        mod = importlib.import_module(f"{name}.app")
        apps.append((name, mod.app))
    return apps


def main() -> int:
    # Ensure service packages resolve (gateway/app.py style modules).
    for name in ("auth", "checkout", "payment", "inventory", "notification", "gateway"):
        pkg = SIM / name
        if str(SIM) not in sys.path:
            sys.path.insert(0, str(SIM))
        # Import as top-level module path: add each service parent already SIM
        _ = pkg
    violations = scan_apps(_load_apps())  # type: ignore[arg-type]
    if violations:
        print("forbidden simulation routes:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("ok sim contract: no forbidden routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
