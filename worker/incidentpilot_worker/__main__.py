"""Entrypoint for incidentpilot-worker / evidence-worker (D1 queue subscription)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from incidentpilot_shared.temporal_queues import TaskQueue, queues_for_process
from incidentpilot_shared.temporal_runtime import run_smoke_subscribe, smoke_subscribe_queues


def _queues_for_role(role: str) -> tuple[TaskQueue, ...]:
    if role == "general":
        return queues_for_process("incidentpilot-worker")
    if role == "evidence":
        return queues_for_process("evidence-worker")
    raise SystemExit(f"unknown worker role: {role}")


async def _run_forever(queues: tuple[TaskQueue, ...]) -> None:
    from incidentpilot_shared.temporal_runtime import build_queue_worker, connect_temporal

    client = await connect_temporal()
    workers = [build_queue_worker(client, q) for q in queues]
    await asyncio.gather(*(w.run() for w in workers))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="incidentpilot_worker")
    parser.add_argument(
        "role",
        nargs="?",
        default="general",
        choices=("general", "evidence", "smoke"),
        help="general (default), evidence, or smoke all worker-owned queues",
    )
    parser.add_argument(
        "smoke_flag",
        nargs="?",
        choices=("smoke",),
        help="with role general|evidence: run subscribe smoke and exit",
    )
    args = parser.parse_args(argv)

    # `python -m incidentpilot_worker smoke` → smoke both general + evidence
    if args.role == "smoke":
        names = run_smoke_subscribe(
            [
                *queues_for_process("incidentpilot-worker"),
                *queues_for_process("evidence-worker"),
            ]
        )
        print("ok worker queue smoke:", ", ".join(names))
        return

    queues = _queues_for_role(args.role)
    if args.smoke_flag == "smoke":
        names = asyncio.run(smoke_subscribe_queues(queues))
        print(f"ok {args.role} queue smoke:", ", ".join(names))
        return

    print(
        f"starting {args.role} worker on: {', '.join(str(q) for q in queues)}",
        file=sys.stderr,
    )
    asyncio.run(_run_forever(queues))


if __name__ == "__main__":
    main()
