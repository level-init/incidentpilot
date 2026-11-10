"""Outbox → Slack delivery (K1). BEST_EFFORT: failures never touch Incident state.

Runs as ``python -m incidentpilot_worker notify`` so ``SLACK_BOT_TOKEN`` stays
off the general AI worker process.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from incidentpilot_adapters.slack import (
    SlackDeliveryError,
    SlackMessage,
    SlackNotifier,
    resolve_slack_notifier,
)
from incidentpilot_shared.domain.outbox import (
    OutboxMessage,
    fetch_pending_outbox,
    mark_outbox_published,
    mark_outbox_retry,
)
from incidentpilot_shared.slack_notify import SLACK_NOTIFY_EVENT
from incidentpilot_worker.db import connect

logger = logging.getLogger(__name__)


def deliver_slack_notify(
    message: OutboxMessage,
    *,
    notifier: SlackNotifier | None = None,
) -> None:
    """Post one ``slack.notify`` outbox payload. Raises ``SlackDeliveryError`` on fault."""
    if message.event_type != SLACK_NOTIFY_EVENT:
        raise ValueError(f"expected {SLACK_NOTIFY_EVENT}, got {message.event_type!r}")
    payload = message.payload or {}
    channel = str(payload.get("channel") or "").strip()
    if not channel:
        raise SlackDeliveryError("slack.notify payload missing channel")
    text = str(payload.get("text") or "")
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        blocks = []
    thread_ts = payload.get("thread_ts")
    client = notifier or resolve_slack_notifier()
    client.post_message(
        channel=channel,
        message=SlackMessage(text=text, blocks=list(blocks)),
        thread_ts=str(thread_ts) if thread_ts else None,
    )


def notify_once(
    *,
    limit: int = 10,
    lease_seconds: float = 15.0,
    notifier: SlackNotifier | None = None,
    aggregate_id: str | None = None,
) -> int:
    """Claim pending outbox rows; deliver Slack notifies; leave Temporal events alone.

    Non-``slack.notify`` rows are released immediately (available_at=now) so the
    Temporal dispatcher can claim them. Returns published Slack count.
    """
    from incidentpilot_shared.domain.outbox import release_outbox_lease

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
        if message.event_type != SLACK_NOTIFY_EVENT:
            with connect() as conn:
                release_outbox_lease(conn, message.id)
                conn.commit()
            continue
        try:
            deliver_slack_notify(message, notifier=notifier)
        except SlackDeliveryError as exc:
            logger.warning(
                "slack notify failed message_id=%s (domain unchanged): %s",
                message.id,
                exc,
            )
            with connect() as conn:
                mark_outbox_retry(conn, message.id, error=str(exc), delay_seconds=5.0)
                conn.commit()
            continue
        except Exception as exc:
            logger.exception("slack notify error message_id=%s", message.id)
            with connect() as conn:
                mark_outbox_retry(conn, message.id, error=str(exc), delay_seconds=5.0)
                conn.commit()
            continue

        with connect() as conn:
            mark_outbox_published(conn, message.id)
            conn.commit()
        published += 1
    return published


async def notify_loop(
    *,
    poll_interval_seconds: float = 1.0,
    limit: int = 10,
    notifier: SlackNotifier | None = None,
) -> None:
    while True:
        await asyncio.to_thread(notify_once, limit=limit, notifier=notifier)
        await asyncio.sleep(poll_interval_seconds)


def incident_state(incident_id: UUID) -> str | None:
    """Read-only helper for tests — notify path must not write this."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        row = cur.fetchone()
        return None if row is None else str(row[0])


def outbox_row(message_id: UUID) -> dict[str, Any] | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, last_error, event_type
            FROM domain.outbox_message WHERE id = %s
            """,
            (str(message_id),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "status": str(row[0]),
            "last_error": row[1],
            "event_type": str(row[2]),
        }
