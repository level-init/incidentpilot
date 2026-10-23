"""Entrypoint for remediation-worker (D1 queue subscription)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from incidentpilot_shared.temporal_queues import queues_for_process
from incidentpilot_shared.temporal_runtime import run_smoke_subscribe


async def _run_forever() -> None:
    from incidentpilot_shared.temporal_runtime import build_queue_worker, connect_temporal

    queues = queues_for_process("remediation-worker")
    client = await connect_temporal()
    workers = [build_queue_worker(client, q) for q in queues]
    await asyncio.gather(*(w.run() for w in workers))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="incidentpilot_remediation")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=("run", "smoke"),
        help="run (default) or smoke-subscribe and exit",
    )
    args = parser.parse_args(argv)

    queues = queues_for_process("remediation-worker")
    if args.command == "smoke":
        names = run_smoke_subscribe(queues)
        print("ok remediation queue smoke:", ", ".join(names))
        return

    print(
        "starting remediation-worker on:",
        ", ".join(str(q) for q in queues),
        file=sys.stderr,
    )
    asyncio.run(_run_forever())


if __name__ == "__main__":
    main()
