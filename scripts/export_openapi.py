#!/usr/bin/env python3
"""Export the FastAPI OpenAPI document to openapi/openapi.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "api"),
    str(ROOT / "shared"),
    str(ROOT / "worker"),
    str(ROOT / "remediation_worker"),
    str(ROOT / "adapters"),
    str(ROOT / "scenario_runner"),
    str(ROOT / "evaluator"),
]

from incidentpilot_api.app import app  # noqa: E402


def main() -> None:
    out = ROOT / "openapi" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    spec = app.openapi()
    out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
