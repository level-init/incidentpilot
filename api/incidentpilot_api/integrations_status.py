"""Integration health/scope metadata for admin UI (M8) — never secrets."""

from __future__ import annotations

import os
from typing import Any

from incidentpilot_api.webhook_auth import (
    alertmanager_auth_mechanisms,
    alertmanager_custom_header_name,
    webhook_auth_configured,
)


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _present(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def alertmanager_integration() -> dict[str, Any]:
    return {
        "key": "alertmanager_webhook",
        "display_name": "Alertmanager webhook",
        "kind": "ingress",
        "configured": webhook_auth_configured(),
        "endpoint": "/webhooks/alerts/alertmanager",
        "scope": {
            "auth_mechanisms_configured": alertmanager_auth_mechanisms(),
            "custom_header_name": alertmanager_custom_header_name(),
            "alertmanager_url_set": _present("ALERTMANAGER_URL"),
        },
        "secrets_exposed": False,
        "notes": "Auth secret values are never returned — only mechanism names.",
    }


def slack_inbound_integration() -> dict[str, Any]:
    open_mode = _truthy("SLACK_COMMANDS_OPEN")
    responders = [
        u.strip()
        for u in os.environ.get("SLACK_COMMAND_RESPONDERS", "").split(",")
        if u.strip()
    ]
    return {
        "key": "slack_inbound",
        "display_name": "Slack inbound (HMAC)",
        "kind": "ingress",
        "configured": _present("SLACK_SIGNING_SECRET"),
        "endpoint": "/webhooks/slack/interactions|/webhooks/slack/commands",
        "scope": {
            "signing_secret_configured": _present("SLACK_SIGNING_SECRET"),
            "commands_open": open_mode,
            "command_responders_count": 0 if open_mode else len(responders),
            "endpoints": [
                "/webhooks/slack/interactions",
                "/webhooks/slack/commands",
            ],
        },
        "secrets_exposed": False,
        "notes": "SLACK_SIGNING_SECRET never returned.",
    }


def slack_outbound_integration() -> dict[str, Any]:
    notifier = (os.environ.get("SLACK_NOTIFIER", "fake") or "fake").strip()
    return {
        "key": "slack_outbound",
        "display_name": "Slack outbound notifier",
        "kind": "egress",
        "configured": notifier == "fake" or _present("SLACK_BOT_TOKEN"),
        "endpoint": None,
        "scope": {
            "notifier_mode": notifier,
            "bot_token_configured": _present("SLACK_BOT_TOKEN"),
            "web_base_url_set": _present("INCIDENTPILOT_WEB_BASE_URL"),
        },
        "secrets_exposed": False,
        "notes": "SLACK_BOT_TOKEN never returned; belongs on notify worker only.",
    }


def list_integration_status() -> list[dict[str, Any]]:
    """Admin-facing connector scope — configured flags only, no secret material."""
    return [
        alertmanager_integration(),
        slack_inbound_integration(),
        slack_outbound_integration(),
    ]
