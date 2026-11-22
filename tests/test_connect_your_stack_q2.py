"""Q2: connect-your-stack doc contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "connect-your-stack.md"


def test_connect_doc_covers_am_slack_and_auth_split() -> None:
    assert DOC.is_file()
    text = DOC.read_text(encoding="utf-8")
    for needle in (
        "self-hosted",
        "/webhooks/alerts/alertmanager",
        "ALERTMANAGER_WEBHOOK_TOKEN",
        "/webhooks/slack/interactions",
        "/webhooks/slack/commands",
        "SLACK_SIGNING_SECRET",
        "webhooks",
        "OIDC",
        "alertmanager.yml",
        "ingress.md",
    ):
        assert needle in text, needle


def test_cross_links_from_readme_and_webhook_docs() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/connect-your-stack.md" in readme
    am = (ROOT / "docs/alert-webhooks.md").read_text(encoding="utf-8")
    assert "connect-your-stack.md" in am
    slack = (ROOT / "docs/slack.md").read_text(encoding="utf-8")
    assert "connect-your-stack.md" in slack
    qs = (ROOT / "docs/quickstart.md").read_text(encoding="utf-8")
    assert "connect-your-stack.md" in qs
