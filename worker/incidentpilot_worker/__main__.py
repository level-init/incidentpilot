"""Entrypoint for incidentpilot-worker / evidence-worker / outbox dispatcher."""

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
    from incidentpilot_shared.temporal_runtime import connect_temporal
    from incidentpilot_worker.worker_factory import build_worker

    client = await connect_temporal()
    workers = [build_worker(client, q) for q in queues]
    await asyncio.gather(*(w.run() for w in workers))


async def _run_dispatcher(*, once: bool) -> None:
    from incidentpilot_shared.temporal_runtime import connect_temporal
    from incidentpilot_worker.outbox_dispatcher import dispatch_loop, dispatch_once

    client = await connect_temporal()
    if once:
        n = await dispatch_once(client)
        print(f"ok outbox dispatch once: published={n}")
        return
    print("starting outbox dispatcher loop", file=sys.stderr)
    await dispatch_loop(client)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="incidentpilot_worker")
    parser.add_argument(
        "role",
        nargs="?",
        default="general",
        choices=("general", "evidence", "smoke", "dispatch"),
        help="general (default), evidence, smoke, or dispatch (outbox→signals)",
    )
    parser.add_argument(
        "smoke_flag",
        nargs="?",
        choices=("smoke", "once"),
        help="with role general|evidence: smoke; with dispatch: once",
    )
    args = parser.parse_args(argv)

    if args.role == "smoke":
        names = run_smoke_subscribe(
            [
                *queues_for_process("incidentpilot-worker"),
                *queues_for_process("evidence-worker"),
            ]
        )
        print("ok worker queue smoke:", ", ".join(names))
        return

    if args.role == "dispatch":
        asyncio.run(_run_dispatcher(once=args.smoke_flag == "once"))
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
