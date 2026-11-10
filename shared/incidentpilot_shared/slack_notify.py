"""Enqueue BEST_EFFORT Slack notify intents on the transactional outbox (K1).

Delivery is owned by the notify process (``python -m incidentpilot_worker notify``).
Failures must never roll back Incident state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from incidentpilot_adapters.slack.templates import (
    render_incident_brief,
    render_incident_update,
)
from incidentpilot_shared.domain.outbox import enqueue_outbox

if TYPE_CHECKING:
    from psycopg import Connection

SLACK_NOTIFY_EVENT: Final[str] = "slack.notify"

SlackTemplate = Literal["brief", "update"]

# Owned by notify process — never inject into general worker AI / LLM context.
AI_FORBIDDEN_SLACK_ENV: Final[frozenset[str]] = frozenset(
    {
        "SLACK_BOT_TOKEN",
        "SLACK_SIGNING_SECRET",
    }
)


def enqueue_slack_notify(
    conn: Connection,
    *,
    incident_id: UUID,
    channel: str,
    template: SlackTemplate,
    public_id: str,
    title: str,
    state: str,
    note: str | None = None,
    summary: str | None = None,
    thread_ts: str | None = None,
    headers: dict[str, Any] | None = None,
) -> UUID:
    """Insert ``slack.notify`` outbox row (caller owns TX). Does not mutate Incident."""
    if template == "brief":
        message = render_incident_brief(
            public_id=public_id,
            title=title,
            state=state,
            summary=summary,
        )
    elif template == "update":
        message = render_incident_update(
            public_id=public_id,
            title=title,
            state=state,
            note=note or summary or title,
        )
    else:
        raise ValueError(f"unknown Slack template: {template!r}")

    payload: dict[str, Any] = {
        "channel": channel,
        "template": template,
        "incident_id": str(incident_id),
        "public_id": public_id,
        "title": title,
        "state": state,
        "text": message.text,
        "blocks": message.blocks,
        "side_effect": "BEST_EFFORT",
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if note is not None:
        payload["note"] = note
    if summary is not None:
        payload["summary"] = summary

    return enqueue_outbox(
        conn,
        aggregate_type="incident",
        aggregate_id=str(incident_id),
        event_type=SLACK_NOTIFY_EVENT,
        payload=payload,
        headers=headers,
    )
