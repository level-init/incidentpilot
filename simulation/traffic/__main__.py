"""python -m traffic — CLI entry for baseline load generator."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sim baseline traffic generator (E4)")
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="seconds to run (0 = until interrupted)",
    )
    parser.add_argument("--rps", type=float, default=1.0, help="approx requests per second")
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=0.05,
        help="fail if failures/requests exceeds this (finite runs)",
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--skip-health-gate",
        action="store_true",
        help="do not require /healthz+/readyz before/after load",
    )
    parser.add_argument(
        "--health-only",
        action="store_true",
        help="only run the baseline health/ready gate, then exit",
    )
    args = parser.parse_args(argv)

    from traffic.generator import check_all_healthz, run_baseline

    if args.health_only:
        bodies = check_all_healthz()
        print(json.dumps(bodies, indent=2, default=str))
        print("ok baseline health gate", file=sys.stderr)
        return 0

    result = run_baseline(
        duration_s=args.duration,
        rps=args.rps,
        max_error_rate=args.max_error_rate,
        concurrency=args.concurrency,
        seed=args.seed,
        require_health_gate=not args.skip_health_gate,
    )
    summary = {
        "duration_s": result.duration_s,
        "requests": result.requests,
        "successes": result.successes,
        "failures": result.failures,
        "error_rate": round(result.error_rate, 4),
        "by_kind": result.by_kind,
        "error_samples": result.error_samples,
    }
    print(json.dumps(summary, indent=2))
    print(
        f"ok baseline traffic requests={result.requests} error_rate={result.error_rate:.4f}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
