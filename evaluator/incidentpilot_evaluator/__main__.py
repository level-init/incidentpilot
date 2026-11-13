"""Evaluator entrypoint — N18 operational pin consumer (GT-capable role)."""

from __future__ import annotations

import argparse
import sys
import time


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="incidentpilot_evaluator")
    parser.add_argument(
        "role",
        choices=("pin",),
        help="pin: claim eval.operational_pin_requested outbox → OperationalEvaluation",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("once", "loop"),
        default="loop",
        help="once = single poll batch; loop = continuous (default)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="seconds between pin polls in loop mode",
    )
    args = parser.parse_args(argv)

    if args.role == "pin":
        from incidentpilot_evaluator.pin_consumer import pin_once

        if args.mode == "once":
            n = pin_once()
            print(f"ok eval pin once: published={n}")
            return 0

        print("starting evaluator pin consumer loop", file=sys.stderr)
        while True:
            pin_once()
            time.sleep(max(args.poll_interval, 0.1))

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
