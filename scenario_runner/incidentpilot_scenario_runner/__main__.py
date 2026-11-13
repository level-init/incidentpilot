"""CLI: scenario-runner (N1/N9) — list / run / scored / eval / reset.

Never reads GroundTruth.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID


def _prepare_path() -> None:
    root = Path(__file__).resolve().parents[2]
    for p in (
        root / "scenario_runner",
        root / "simulation",
        root / "shared",
        root / "adapters",
    ):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


def main(argv: list[str] | None = None) -> int:
    _prepare_path()
    parser = argparse.ArgumentParser(
        description="IncidentPilot scenario-runner — no GroundTruth access"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list scenarios.scenario catalog")

    p_defs = sub.add_parser("definitions", help="list YAML scenario definitions (N9)")
    p_defs.add_argument(
        "--name",
        default=None,
        help="resolve one name/alias (e.g. bad-deployment)",
    )

    p_run = sub.add_parser(
        "run",
        help="baseline gate then inject fault (FAILED if baseline unhealthy)",
    )
    p_run.add_argument("scenario", help="scenario key (e.g. bad_deploy)")
    p_run.add_argument(
        "--no-inject",
        action="store_true",
        help="stop after baseline pass (no fault)",
    )

    p_scored = sub.add_parser(
        "scored",
        help="N9 scored vertical: isolation → FAULT_INJECTED → Level-2 harness",
    )
    p_scored.add_argument(
        "name",
        nargs="?",
        default="bad-deployment",
        help="scenario key or alias (default bad-deployment)",
    )
    p_scored.add_argument(
        "--skip-isolation",
        action="store_true",
        help="skip isolation scan gate (tests only)",
    )
    p_scored.add_argument(
        "--inject",
        action="store_true",
        help="also call live sim injector (default: mock FAULT_INJECTED)",
    )

    p_eval = sub.add_parser(
        "eval",
        help="N9 pin Operational+Postmortem eval for last scored run",
    )
    p_eval.add_argument(
        "--name",
        default=None,
        help="optional scenario name/alias for cache labeling",
    )
    p_eval.add_argument("--run-id", default=None, help="override scenario_run UUID")
    p_eval.add_argument("--incident-id", default=None, help="override incident UUID")

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

    if args.cmd == "definitions":
        from incidentpilot_scenario_runner.definitions import (
            load_all_definitions,
            resolve_scenario_name,
        )

        if args.name:
            d = resolve_scenario_name(args.name)
            print(json.dumps(d.raw or {"key": d.key}, indent=2, default=str))
            return 0
        rows = [
            {
                "key": d.key,
                "aliases": list(d.aliases),
                "autonomy_level": d.autonomy_level,
                "harness": d.harness,
                "injector_id": d.injector_id,
            }
            for d in load_all_definitions()
        ]
        print(json.dumps({"definitions": rows}, indent=2))
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
            f"ok reset stamped={out['runs_stamped']} history={out['scenario_run_history_count']}",
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
                f"scenario_run FAILED kind={outcome.failure_kind} (not EVALUATED)",
                file=sys.stderr,
            )
            return 2
        print(f"ok scenario_run {outcome.status} id={outcome.run_id}", file=sys.stderr)
        return 0

    if args.cmd == "scored":
        from incidentpilot_scenario_runner.scored import run_scored_vertical

        result = run_scored_vertical(
            args.name,
            require_isolation=not args.skip_isolation,
            inject=args.inject,
        )
        print(json.dumps(result.as_dict(), indent=2))
        print(
            f"ok scored vertical {result.scenario_key} "
            f"run={result.run_id} incident={result.incident_id} "
            f"(pending make eval)",
            file=sys.stderr,
        )
        return 0

    if args.cmd == "eval":
        from incidentpilot_scenario_runner.scored import evaluate_scored_vertical

        result = evaluate_scored_vertical(
            run_id=UUID(args.run_id) if args.run_id else None,
            incident_id=UUID(args.incident_id) if args.incident_id else None,
            name=args.name,
        )
        print(json.dumps(result.as_dict(), indent=2))
        print(
            f"ok EVALUATED family={result.family_count} "
            f"ops_pass={result.passed_operational} "
            f"pm_pass={result.passed_postmortem} "
            f"manifest={result.environment_manifest_id}",
            file=sys.stderr,
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
