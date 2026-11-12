"""CLI: scenario-runner (N1) — list / run / reset. Never reads GroundTruth."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID


def _prepare_path() -> None:
    root = Path(__file__).resolve().parents[2]
    for p in (root / "scenario_runner", root / "simulation", root / "shared"):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


def main(argv: list[str] | None = None) -> int:
    _prepare_path()
    parser = argparse.ArgumentParser(
        description="IncidentPilot scenario-runner (N1) — no GroundTruth access"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list scenario catalog")

    p_run = sub.add_parser(
        "run",
        help="baseline gate then inject fault (FAILED if baseline unhealthy)",
    )
    p_run.add_argument(
        "scenario",
        help="scenario key (e.g. bad_deploy)",
    )
    p_run.add_argument(
        "--no-inject",
        action="store_true",
        help="stop after baseline pass (no fault)",
    )

    p_reset = sub.add_parser(
        "reset",
        help="clear sim faults; keep ScenarioRun history",
    )
    p_reset.add_argument(
        "--run-id",
        default=None,
        help="optional scenario_run UUID to stamp reset_at",
    )

    p_show = sub.add_parser("show", help="show a scenario_run by id")
    p_show.add_argument("run_id")

    args = parser.parse_args(argv)

    from incidentpilot_scenario_runner.db import (
        get_runner_conn,
        get_scenario_run,
        list_scenarios,
    )
    from incidentpilot_scenario_runner.runner import reset_environment, run_scenario

    if args.cmd == "list":
        with get_runner_conn() as conn:
            rows = list_scenarios(conn)
        print(json.dumps({"scenarios": rows}, indent=2, default=str))
        return 0

    if args.cmd == "show":
        with get_runner_conn() as conn:
            row = get_scenario_run(conn, UUID(args.run_id))
        print(json.dumps(row, indent=2, default=str))
        return 0

    if args.cmd == "reset":
        rid = UUID(args.run_id) if args.run_id else None
        out = reset_environment(run_id=rid)
        print(json.dumps(out, indent=2, default=str))
        print(
            f"ok reset stamped={out['runs_stamped']} "
            f"history={out['scenario_run_history_count']}",
            file=sys.stderr,
        )
        return 0

    if args.cmd == "run":
        outcome = run_scenario(args.scenario, inject=not args.no_inject)
        payload = {
            "run_id": str(outcome.run_id),
            "scenario_key": outcome.scenario_key,
            "status": outcome.status,
            "failure_kind": outcome.failure_kind,
            "failure_detail": outcome.failure_detail,
            "baseline_ok": outcome.baseline_ok,
        }
        print(json.dumps(payload, indent=2))
        if outcome.status == "FAILED":
            print(
                f"scenario_run FAILED kind={outcome.failure_kind} "
                f"(not EVALUATED)",
                file=sys.stderr,
            )
            return 2
        print(f"ok scenario_run {outcome.status} id={outcome.run_id}", file=sys.stderr)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
