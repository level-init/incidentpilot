#!/usr/bin/env python3
"""Fail if simulation exposes GroundTruth / root-cause cheat routes or fields (E6)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "simulation"
sys.path.insert(0, str(SIM))

from common.contract import scan_all  # noqa: E402

SERVICES = ("auth", "checkout", "payment", "inventory", "notification", "gateway")


def _load_apps() -> list[tuple[str, object]]:
    apps: list[tuple[str, object]] = []
    for name in SERVICES:
        mod = importlib.import_module(f"{name}.app")
        apps.append((name, mod.app))
    return apps


def main() -> int:
    violations = scan_all(sim_root=SIM, apps=_load_apps())  # type: ignore[arg-type]
    if violations:
        print("forbidden simulation contract violations:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("ok sim contract: no forbidden routes/fields/sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
