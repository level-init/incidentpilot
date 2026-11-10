"""SlackNotifier protocol + fake (fault inject) + env resolve (K1).

``SLACK_BOT_TOKEN`` belongs on the **notify** process only — never on the
general worker AI / LLM context.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from incidentpilot_adapters.slack.templates import SlackMessage


class SlackDeliveryError(RuntimeError):
    """Outbound Slack post failed (BEST_EFFORT — do not roll back domain)."""


@dataclass(frozen=True, slots=True)
class SlackPostResult:
    ok: bool
    channel: str
    ts: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SlackNotifier(Protocol):
    """Outbound chat.postMessage client (no domain writes)."""

    def post_message(
        self,
        *,
        channel: str,
        message: SlackMessage,
        thread_ts: str | None = None,
    ) -> SlackPostResult: ...


@dataclass
class FakeSlackNotifier:
    """In-memory notifier; set ``fail=True`` to fault-inject delivery."""

    fail: bool = False
    fail_message: str = "fault-injected Slack failure"
    posts: list[dict[str, Any]] = field(default_factory=list)

    def post_message(
        self,
        *,
        channel: str,
        message: SlackMessage,
        thread_ts: str | None = None,
    ) -> SlackPostResult:
        if self.fail:
            raise SlackDeliveryError(self.fail_message)
        ts = f"fake-{len(self.posts) + 1}"
        self.posts.append(
            {
                "channel": channel,
                "text": message.text,
                "blocks": message.blocks,
                "thread_ts": thread_ts,
                "ts": ts,
            }
        )
        return SlackPostResult(ok=True, channel=channel, ts=ts, raw={"ok": True, "ts": ts})


class HttpSlackNotifier:
    """Minimal chat.postMessage via Slack Web API."""

    def __init__(self, token: str, *, api_base: str = "https://slack.com/api") -> None:
        self._token = token
        self._api_base = api_base.rstrip("/")

    def post_message(
        self,
        *,
        channel: str,
        message: SlackMessage,
        thread_ts: str | None = None,
    ) -> SlackPostResult:
        body: dict[str, Any] = {
            "channel": channel,
            "text": message.text,
            "blocks": message.blocks,
        }
        if thread_ts:
            body["thread_ts"] = thread_ts
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self._api_base}/chat.postMessage",
            data=data,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise SlackDeliveryError(f"Slack HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise SlackDeliveryError(f"Slack transport: {exc}") from exc
        if not raw.get("ok"):
            raise SlackDeliveryError(f"Slack API error: {raw.get('error', 'unknown')}")
        return SlackPostResult(
            ok=True,
            channel=str(raw.get("channel") or channel),
            ts=str(raw["ts"]) if raw.get("ts") else None,
            raw=dict(raw),
        )


_FAKE: FakeSlackNotifier | None = None


def set_fake_slack_notifier(notifier: FakeSlackNotifier | None) -> None:
    global _FAKE
    _FAKE = notifier


def get_fake_slack_notifier() -> FakeSlackNotifier:
    global _FAKE
    if _FAKE is None:
        _FAKE = FakeSlackNotifier()
    return _FAKE


def resolve_slack_notifier() -> SlackNotifier:
    """``SLACK_NOTIFIER=fake`` (default) or ``http`` requiring ``SLACK_BOT_TOKEN``."""
    mode = (os.environ.get("SLACK_NOTIFIER") or "fake").strip().lower()
    if mode in ("fake", "test"):
        return get_fake_slack_notifier()
    if mode in ("http", "live"):
        token = (os.environ.get("SLACK_BOT_TOKEN") or "").strip()
        if not token:
            raise SlackDeliveryError("SLACK_BOT_TOKEN required when SLACK_NOTIFIER=http")
        return HttpSlackNotifier(token)
    raise SlackDeliveryError(f"unknown SLACK_NOTIFIER={mode!r}")
