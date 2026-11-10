"""Outbound Slack notifier (K1) — dedicated cred; never in AI tool context."""

from incidentpilot_adapters.slack.notifier import (
    FakeSlackNotifier,
    SlackDeliveryError,
    SlackNotifier,
    SlackPostResult,
    get_fake_slack_notifier,
    resolve_slack_notifier,
    set_fake_slack_notifier,
)
from incidentpilot_adapters.slack.templates import (
    SlackMessage,
    render_incident_brief,
    render_incident_evidence,
    render_incident_postmortem,
    render_incident_recovery,
    render_incident_status,
    render_incident_update,
)

__all__ = [
    "FakeSlackNotifier",
    "SlackDeliveryError",
    "SlackMessage",
    "SlackNotifier",
    "SlackPostResult",
    "get_fake_slack_notifier",
    "render_incident_brief",
    "render_incident_evidence",
    "render_incident_postmortem",
    "render_incident_recovery",
    "render_incident_status",
    "render_incident_update",
    "resolve_slack_notifier",
    "set_fake_slack_notifier",
]
