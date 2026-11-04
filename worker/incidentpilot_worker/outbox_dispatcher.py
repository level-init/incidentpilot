"""Outbox dispatcher: pending domain.outbox_message → Temporal signals (D4).

At-least-once delivery. Workflow signal handlers must dedupe by message_id.
Does not apply domain transitions — those already committed with the outbox row.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final
from uuid import UUID

from temporalio.client import Client
from temporalio.service import RPCError

from incidentpilot_shared.domain.outbox import (
    OutboxMessage,
    fetch_pending_outbox,
    mark_outbox_published,
    mark_outbox_retry,
)
from incidentpilot_shared.incident_workflow import incident_workflow_id
from incidentpilot_shared.temporal_queues import TaskQueue
from incidentpilot_worker.db import connect
from incidentpilot_worker.domain_events import DomainEventEnvelope

logger = logging.getLogger(__name__)

# event_type → workflow signal name
SIGNAL_MAP: Final[dict[str, str]] = {
    "incident.transitioned": "domain_event",
    "incident.created": "domain_event",
}


def workflow_id_for(message: OutboxMessage) -> str:
    if message.aggregate_type == "incident":
        return incident_workflow_id(message.aggregate_id)
    return f"{message.aggregate_type}-{message.aggregate_id}"


async def deliver_outbox_signal(client: Client, message: OutboxMessage) -> None:
    signal_name = SIGNAL_MAP.get(message.event_type)
    if signal_name is None:
        raise ValueError(f"no signal mapping for event_type={message.event_type!r}")

    envelope = DomainEventEnvelope(
        message_id=str(message.id),
        event_type=message.event_type,
        aggregate_type=message.aggregate_type,
        aggregate_id=message.aggregate_id,
        payload=message.payload,
    )
    handle = client.get_workflow_handle(workflow_id_for(message))
    await handle.signal(signal_name, envelope)


async def dispatch_once(
    client: Client,
    *,
    limit: int = 10,
    lease_seconds: float = 15.0,
    aggregate_id: str | None = None,
) -> int:
    """Claim a batch, signal workflows, mark published. Returns published count."""
    with connect() as conn:
        messages = fetch_pending_outbox(
            conn,
            limit=limit,
            lease_seconds=lease_seconds,
            aggregate_id=aggregate_id,
        )
        conn.commit()

    published = 0
    for message in messages:
        try:
            await deliver_outbox_signal(client, message)
        except RPCError as exc:
            logger.warning(
                "outbox signal failed message_id=%s workflow=%s: %s",
                message.id,
                workflow_id_for(message),
                exc,
            )
            with connect() as conn:
                mark_outbox_retry(conn, message.id, error=str(exc), delay_seconds=2.0)
                conn.commit()
            continue
        except Exception as exc:
            logger.exception("outbox deliver error message_id=%s", message.id)
            with connect() as conn:
                mark_outbox_retry(conn, message.id, error=str(exc), delay_seconds=5.0)
                conn.commit()
            continue

        with connect() as conn:
            mark_outbox_published(conn, message.id)
            conn.commit()
        published += 1
    return published


async def dispatch_loop(
    client: Client,
    *,
    poll_interval_seconds: float = 1.0,
    limit: int = 10,
) -> None:
    while True:
        await dispatch_once(client, limit=limit)
        await asyncio.sleep(poll_interval_seconds)


def outbox_status(message_id: UUID) -> str | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM domain.outbox_message WHERE id = %s",
            (str(message_id),),
        )
        row = cur.fetchone()
        return None if row is None else str(row[0])


# Re-export task queue constant for docs/tests
DEFAULT_DISPATCH_TASK_QUEUE = TaskQueue.GENERAL
