"""Slack message templates for incident brief / update (K1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SlackMessage:
    """Rendered chat.postMessage body (text + optional Block Kit)."""

    text: str
    blocks: list[dict[str, Any]]


def render_incident_brief(
    *,
    public_id: str,
    title: str,
    state: str,
    summary: str | None = None,
) -> SlackMessage:
    """Initial / high-signal incident brief."""
    body = summary.strip() if summary else title
    text = f"*{public_id}* — {title}\nState: `{state}`\n{body}"
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{public_id}: {title}"[:150]},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*State*\n`{state}`"},
                {"type": "mrkdwn", "text": "*Kind*\nbrief"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": body[:2900]},
        },
    ]
    return SlackMessage(text=text, blocks=blocks)


def render_incident_update(
    *,
    public_id: str,
    title: str,
    state: str,
    note: str,
) -> SlackMessage:
    """Status / recovery update on an existing incident thread intent."""
    text = f"*{public_id}* update — `{state}`\n{note}"
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
            "elements": [{"type": "mrkdwn", "text": "kind: update"}],
        },
    ]
    return SlackMessage(text=text, blocks=blocks)
