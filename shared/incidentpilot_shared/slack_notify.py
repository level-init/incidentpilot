"""Enqueue BEST_EFFORT Slack notify intents on the transactional outbox (K1/K4).

Delivery is owned by the notify process (``python -m incidentpilot_worker notify``).
Failures must never roll back Incident state. K4 adds lifecycle templates,
thread roots in ``domain.slack_incident_thread``, and UI deep links.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from incidentpilot_adapters.slack.templates import (
    SlackMessage,
    render_incident_brief,
    render_incident_evidence,
    render_incident_postmortem,
    render_incident_recovery,
    render_incident_status,
    render_incident_update,
)
from incidentpilot_shared.domain.outbox import enqueue_outbox

if TYPE_CHECKING:
    from psycopg import Connection

SLACK_NOTIFY_EVENT: Final[str] = "slack.notify"

SlackTemplate = Literal[
    "brief",
    "update",
    "status",
    "evidence",
    "recovery",
    "postmortem",
]

LIFECYCLE_TEMPLATES: Final[tuple[SlackTemplate, ...]] = (
    "brief",
    "evidence",
    "status",
    "recovery",
    "postmortem",
)

# Owned by notify process — never inject into general worker AI / LLM context.
AI_FORBIDDEN_SLACK_ENV: Final[frozenset[str]] = frozenset(
    {
        "SLACK_BOT_TOKEN",
        "SLACK_SIGNING_SECRET",
    }
)

_DEFAULT_WEB_BASE = "http://localhost:3000"


def incident_ui_url(public_id: str, *, base: str | None = None) -> str:
    """Deep link into the ops UI for an incident public id."""
    if base is not None:
        root = base
    else:
        root = os.environ.get("INCIDENTPILOT_WEB_BASE_URL") or _DEFAULT_WEB_BASE
    return f"{root.rstrip('/')}/incidents/{public_id}"


def get_slack_incident_thread(
    conn: Connection, *, incident_id: UUID
) -> tuple[str, str] | None:
    """Return ``(channel, thread_ts)`` for the incident root, if any."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT channel, thread_ts
            FROM domain.slack_incident_thread
            WHERE incident_id = %s
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1])


def upsert_slack_incident_thread(
    conn: Connection,
    *,
    incident_id: UUID,
    channel: str,
    thread_ts: str,
    commit: bool = False,
) -> None:
    """Remember the Slack root ``ts`` for subsequent threaded replies."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.slack_incident_thread (
                incident_id, channel, thread_ts
            ) VALUES (%s, %s, %s)
            ON CONFLICT (incident_id) DO UPDATE
            SET channel = EXCLUDED.channel,
                thread_ts = EXCLUDED.thread_ts,
                updated_at = now()
            """,
            (str(incident_id), channel, thread_ts),
        )
    if commit:
        conn.commit()


def _render(
    *,
    template: SlackTemplate,
    public_id: str,
    title: str,
    state: str,
    note: str | None,
    summary: str | None,
    ui_url: str | None,
) -> SlackMessage:
    body = note or summary or title
    if template == "brief":
        return render_incident_brief(
            public_id=public_id,
            title=title,
            state=state,
            summary=summary,
            ui_url=ui_url,
        )
    if template == "update":
        return render_incident_update(
            public_id=public_id,
            title=title,
            state=state,
            note=body,
            ui_url=ui_url,
        )
    if template == "status":
        return render_incident_status(
            public_id=public_id,
            title=title,
            state=state,
            note=body,
            ui_url=ui_url,
        )
    if template == "evidence":
        return render_incident_evidence(
            public_id=public_id,
            title=title,
            state=state,
            note=body,
            ui_url=ui_url,
        )
    if template == "recovery":
        return render_incident_recovery(
            public_id=public_id,
            title=title,
            state=state,
            note=body,
            ui_url=ui_url,
        )
    if template == "postmortem":
        return render_incident_postmortem(
            public_id=public_id,
            title=title,
            state=state,
            note=body,
            ui_url=ui_url,
        )
    raise ValueError(f"unknown Slack template: {template!r}")


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
    ui_url: str | None = None,
    headers: dict[str, Any] | None = None,
    bind_thread: bool = True,
) -> UUID:
    """Insert ``slack.notify`` outbox row (caller owns TX). Does not mutate Incident.

    Non-brief templates auto-bind ``thread_ts`` from ``slack_incident_thread`` when
    ``bind_thread`` is true and ``thread_ts`` is omitted.
    """
    if thread_ts is None and bind_thread and template != "brief":
        existing = get_slack_incident_thread(conn, incident_id=incident_id)
        if existing is not None:
            thread_ts = existing[1]

    link = ui_url if ui_url is not None else incident_ui_url(public_id)
    message = _render(
        template=template,
        public_id=public_id,
        title=title,
        state=state,
        note=note,
        summary=summary,
        ui_url=link,
    )

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
        "ui_url": link,
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


def enqueue_slack_lifecycle_thread(
    conn: Connection,
    *,
    incident_id: UUID,
    channel: str,
    public_id: str,
    title: str,
    states: dict[str, str] | None = None,
    notes: dict[str, str] | None = None,
    commit: bool = False,
) -> list[UUID]:
    """Enqueue a coherent brief → evidence → status → recovery → postmortem sequence.

    Used by demos/tests. Callers must run ``notify`` after brief so the thread
    root exists before reply rows are delivered (or pass explicit thread_ts).
    """
    state_map = {
        "brief": "INVESTIGATING",
        "evidence": "INVESTIGATING",
        "status": "MITIGATING",
        "recovery": "VALIDATING",
        "postmortem": "POSTMORTEM",
    }
    if states:
        state_map.update(states)
    note_map = {
        "brief": title,
        "evidence": "New evidence attached to the incident.",
        "status": "Remediation in progress.",
        "recovery": "Validation window / recovery check.",
        "postmortem": f"Postmortem draft for {public_id}.",
    }
    if notes:
        note_map.update(notes)

    ids: list[UUID] = []
    for kind in LIFECYCLE_TEMPLATES:
        ids.append(
            enqueue_slack_notify(
                conn,
                incident_id=incident_id,
                channel=channel,
                template=kind,  # type: ignore[arg-type]
                public_id=public_id,
                title=title,
                state=state_map[kind],
                note=note_map[kind],
                summary=note_map[kind] if kind == "brief" else None,
                bind_thread=(kind != "brief"),
            )
        )
    if commit:
        conn.commit()
    return ids
