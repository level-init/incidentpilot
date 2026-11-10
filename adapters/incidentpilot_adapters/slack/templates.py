"""Slack message templates for incident lifecycle updates (K1/K4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SlackMessage:
    """Rendered chat.postMessage body (text + optional Block Kit)."""

    text: str
    blocks: list[dict[str, Any]]


def _ui_context(ui_url: str | None) -> list[dict[str, Any]]:
    if not ui_url:
        return []
    return [
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"<{ui_url}|Open in IncidentPilot>"}],
        }
    ]


def _kind_fields(*, state: str, kind: str) -> dict[str, Any]:
    return {
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*State*\n`{state}`"},
            {"type": "mrkdwn", "text": f"*Kind*\n{kind}"},
        ],
    }


def render_incident_brief(
    *,
    public_id: str,
    title: str,
    state: str,
    summary: str | None = None,
    ui_url: str | None = None,
) -> SlackMessage:
    """Root thread message — high-signal incident brief."""
    body = summary.strip() if summary else title
    text = f"*{public_id}* — {title}\nState: `{state}`\n{body}"
    if ui_url:
        text = f"{text}\n{ui_url}"
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{public_id}: {title}"[:150]},
        },
        _kind_fields(state=state, kind="brief"),
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": body[:2900]},
        },
        *_ui_context(ui_url),
    ]
    return SlackMessage(text=text, blocks=blocks)


def render_incident_update(
    *,
    public_id: str,
    title: str,
    state: str,
    note: str,
    ui_url: str | None = None,
) -> SlackMessage:
    """Backward-compatible alias for status updates (K1)."""
    return render_incident_status(
        public_id=public_id,
        title=title,
        state=state,
        note=note,
        ui_url=ui_url,
    )


def render_incident_status(
    *,
    public_id: str,
    title: str,
    state: str,
    note: str,
    ui_url: str | None = None,
) -> SlackMessage:
    """Threaded status update."""
    text = f"*{public_id}* status — `{state}`\n{note}"
    if ui_url:
        text = f"{text}\n{ui_url}"
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{public_id}* (`{state}`) — {title}\n{note}"[:3000],
            },
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "kind: status"}],
        },
        *_ui_context(ui_url),
    ]
    return SlackMessage(text=text, blocks=blocks)


def render_incident_evidence(
    *,
    public_id: str,
    title: str,
    state: str,
    note: str,
    ui_url: str | None = None,
) -> SlackMessage:
    """Threaded evidence highlight."""
    text = f"*{public_id}* evidence — `{state}`\n{note}"
    if ui_url:
        text = f"{text}\n{ui_url}"
    blocks: list[dict[str, Any]] = [
        _kind_fields(state=state, kind="evidence"),
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": note[:2900]},
        },
        *_ui_context(ui_url),
    ]
    return SlackMessage(text=text, blocks=blocks)


def render_incident_recovery(
    *,
    public_id: str,
    title: str,
    state: str,
    note: str,
    ui_url: str | None = None,
) -> SlackMessage:
    """Threaded recovery / validation note."""
    text = f"*{public_id}* recovery — `{state}`\n{note}"
    if ui_url:
        text = f"{text}\n{ui_url}"
    blocks: list[dict[str, Any]] = [
        _kind_fields(state=state, kind="recovery"),
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{title}*\n{note}"[:2900]},
        },
        *_ui_context(ui_url),
    ]
    return SlackMessage(text=text, blocks=blocks)


def render_incident_postmortem(
    *,
    public_id: str,
    title: str,
    state: str,
    note: str,
    ui_url: str | None = None,
) -> SlackMessage:
    """Threaded postmortem link / draft pointer."""
    text = f"*{public_id}* postmortem — `{state}`\n{note}"
    if ui_url:
        text = f"{text}\n{ui_url}"
    blocks: list[dict[str, Any]] = [
        _kind_fields(state=state, kind="postmortem"),
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": note[:2900]},
        },
        *_ui_context(ui_url),
    ]
    return SlackMessage(text=text, blocks=blocks)
