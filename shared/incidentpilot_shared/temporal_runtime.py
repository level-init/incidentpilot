"""Temporal client/worker helpers — local Compose, self-host, or Temporal Cloud (O6)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from incidentpilot_shared.temporal_queues import TaskQueue


def temporal_address() -> str:
    # Helm historically emitted TEMPORAL_HOST; runtime + Compose use TEMPORAL_ADDRESS.
    return (
        os.environ.get("TEMPORAL_ADDRESS")
        or os.environ.get("TEMPORAL_HOST")
        or "localhost:7233"
    )


def temporal_namespace() -> str:
    return os.environ.get("TEMPORAL_NAMESPACE", "default")


def temporal_api_key() -> str | None:
    key = os.environ.get("TEMPORAL_API_KEY", "").strip()
    return key or None


def temporal_tls_enabled(
    *,
    address: str | None = None,
    api_key: str | None = None,
) -> bool:
    """TLS is required for Temporal Cloud; optional override via TEMPORAL_TLS."""
    raw = os.environ.get("TEMPORAL_TLS", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    host = address or temporal_address()
    if api_key is None:
        api_key = temporal_api_key()
    if api_key:
        return True
    return ".tmprl.cloud" in host or host.endswith(".temporal.io")


def temporal_hosting_mode() -> str:
    """Return ``cloud`` or ``selfhosted`` (docs / smoke labeling)."""
    explicit = os.environ.get("TEMPORAL_HOSTING", "").strip().lower()
    if explicit in ("cloud", "selfhosted", "self-hosted"):
        return "cloud" if explicit.startswith("cloud") else "selfhosted"
    if temporal_api_key() or temporal_tls_enabled():
        addr = temporal_address()
        if ".tmprl.cloud" in addr or "temporal.io" in addr:
            return "cloud"
    return "selfhosted"


@activity.defn(name="queue_subscribe_ping")
async def queue_subscribe_ping() -> str:
    """Placeholder activity so Workers can register (Temporal requires ≥1 handler)."""
    return "ok"


async def connect_temporal(
    address: str | None = None,
    namespace: str | None = None,
    *,
    api_key: str | None = None,
    tls: bool | None = None,
) -> Client:
    """Connect to Temporal (Compose / self-host plaintext, or Cloud TLS + API key)."""
    target = address or temporal_address()
    ns = namespace or temporal_namespace()
    key = api_key if api_key is not None else temporal_api_key()
    use_tls = temporal_tls_enabled(address=target, api_key=key) if tls is None else tls

    kwargs: dict = {
        "namespace": ns,
    }
    if use_tls:
        kwargs["tls"] = True
    if key:
        kwargs["api_key"] = key
        kwargs["tls"] = True

    return await Client.connect(target, **kwargs)


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
