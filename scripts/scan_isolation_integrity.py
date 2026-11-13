#!/usr/bin/env python3
"""N8: static isolation scan — GT must not enter investigation path source."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Investigation / runner paths (evaluator + eval HTTP routes excluded).
SCAN_ROOTS = (
    ROOT / "api" / "incidentpilot_api",
    ROOT / "worker",
    ROOT / "remediation_worker",
    ROOT / "scenario_runner",
    ROOT / "adapters",
    ROOT / "web" / "src",
)

ALLOW_FILES = {
    # Runner only probes denial; must not read GT for scoring.
    ROOT / "scenario_runner" / "incidentpilot_scenario_runner" / "db.py",
}

# Eval HTTP is entitled GT access — skip.
SKIP_PREFIXES = (
    ROOT / "api" / "incidentpilot_api" / "routes" / "eval.py",
)

FORBIDDEN = [
    (re.compile(r"FROM\s+eval\.ground_truth", re.I), "SQL SELECT of eval.ground_truth"),
    (re.compile(r"INSERT\s+INTO\s+eval\.ground_truth", re.I), "SQL INSERT into eval.ground_truth"),
    (re.compile(r"\banswer_key\b", re.I), "answer_key marker"),
    (re.compile(r"\bactual_root_cause\b", re.I), "actual_root_cause marker"),
    (re.compile(r"get_ground_truth\s*\("), "get_ground_truth call"),
    (
        re.compile(r"incidentpilot_evaluator\.ground_truth"),
        "evaluator ground_truth import",
    ),
]


def _iter_files() -> list[Path]:
    out: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                continue
            if any(path == p or p in path.parents for p in SKIP_PREFIXES):
                # SKIP_PREFIXES are files; handle file equality
                continue
            if path.resolve() == (ROOT / "api/incidentpilot_api/routes/eval.py").resolve():
                continue
            out.append(path)
    return out


def main() -> int:
    violations: list[str] = []
    for path in _iter_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT)
        allowed = path.resolve() in {p.resolve() for p in ALLOW_FILES}
        for cre, label in FORBIDDEN:
            for i, line in enumerate(text.splitlines(), start=1):
                if not cre.search(line):
                    continue
                # Allowed file may mention ground_truth only for denial probe.
                if allowed and "ground_truth" in line and (
                    "assert_ground_truth_denied" in text
                    or "SELECT 1 FROM eval.ground_truth" in line
                ):
                    if "INSERT" in line.upper() or "answer_payload" in line:
                        violations.append(f"{rel}:{i}: {label}: {line.strip()}")
                    continue
                if allowed and "eval.ground_truth" in line and "SELECT 1" in line:
                    continue
                violations.append(f"{rel}:{i}: {label}: {line.strip()}")

    if violations:
        print("isolation integrity scan FAILED:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    print("ok isolation integrity scan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
