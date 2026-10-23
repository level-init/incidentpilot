"""Minimal Temporal client/worker helpers for queue subscription smoke (D1)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from incidentpilot_shared.temporal_queues import TaskQueue


def temporal_address() -> str:
    return os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")


def temporal_namespace() -> str:
    return os.environ.get("TEMPORAL_NAMESPACE", "default")


@activity.defn(name="queue_subscribe_ping")
async def queue_subscribe_ping() -> str:
    """Placeholder activity so Workers can register (Temporal requires ≥1 handler)."""
    return "ok"


async def connect_temporal(
    address: str | None = None,
    namespace: str | None = None,
) -> Client:
    return await Client.connect(
        address or temporal_address(),
        namespace=namespace or temporal_namespace(),
    )


def build_queue_worker(client: Client, task_queue: TaskQueue | str) -> Worker:
    """Worker subscribed to one queue with the D1 placeholder activity only."""
    return Worker(
        client,
        task_queue=str(task_queue),
        workflows=[],
        activities=[queue_subscribe_ping],
    )


async def smoke_subscribe_queues(
    queues: Sequence[TaskQueue | str],
    *,
    address: str | None = None,
    namespace: str | None = None,
    hold_seconds: float = 1.0,
) -> list[str]:
    """Connect and run Workers on each queue briefly (placeholder activity only).

    Proves the process can subscribe without errors. Cancels after ``hold_seconds``.
    Returns the queue names successfully started.
    """
    if not queues:
        raise ValueError("at least one task queue is required")

    names = [str(q) for q in queues]
    client = await connect_temporal(address=address, namespace=namespace)
    workers = [build_queue_worker(client, name) for name in names]

    async def _run_all() -> None:
        await asyncio.gather(*(worker.run() for worker in workers))

    task = asyncio.create_task(_run_all())
    try:
        await asyncio.sleep(hold_seconds)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return names


def run_smoke_subscribe(
    queues: Sequence[TaskQueue | str],
    *,
    hold_seconds: float = 1.0,
) -> list[str]:
    return asyncio.run(smoke_subscribe_queues(queues, hold_seconds=hold_seconds))
