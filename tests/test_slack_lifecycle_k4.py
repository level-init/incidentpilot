"""K4: coherent Slack lifecycle thread — brief/evidence/status/recovery/postmortem."""

from __future__ import annotations

import os
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")

from incidentpilot_adapters.slack import (  # noqa: E402
    FakeSlackNotifier,
    render_incident_brief,
    render_incident_evidence,
    set_fake_slack_notifier,
)
from incidentpilot_shared.slack_notify import (  # noqa: E402
    LIFECYCLE_TEMPLATES,
    enqueue_slack_lifecycle_thread,
    get_slack_incident_thread,
    incident_ui_url,
)
from incidentpilot_worker.slack_notifier import notify_once  # noqa: E402


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.slack_incident_thread LIMIT 1")
            return True
    except Exception:
        return False


def test_incident_ui_url_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INCIDENTPILOT_WEB_BASE_URL", raising=False)
    assert incident_ui_url("INC-ABC") == "http://localhost:3000/incidents/INC-ABC"


def test_incident_ui_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INCIDENTPILOT_WEB_BASE_URL", "https://ops.example/app/")
    assert incident_ui_url("INC-1") == "https://ops.example/app/incidents/INC-1"


def test_templates_include_ui_link() -> None:
    brief = render_incident_brief(
        public_id="INC-1",
        title="checkout 5xx",
        state="INVESTIGATING",
        summary="errors rising",
        ui_url="http://localhost:3000/incidents/INC-1",
    )
    assert "http://localhost:3000/incidents/INC-1" in brief.text
    evidence = render_incident_evidence(
        public_id="INC-1",
        title="checkout 5xx",
        state="INVESTIGATING",
        note="EV-9 deploy fingerprint",
        ui_url="http://localhost:3000/incidents/INC-1",
    )
    assert "evidence" in str(evidence.blocks).lower()


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0017 not reachable")
def test_lifecycle_thread_is_coherent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INCIDENTPILOT_WEB_BASE_URL", "http://ui.test")
    iid = uuid.uuid4()
    public_id = f"INC-K4-{iid.hex[:8]}"
    fake = FakeSlackNotifier()
    set_fake_slack_notifier(fake)

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'K4 lifecycle', 1)
            """,
            (str(iid), public_id),
        )
        ids = enqueue_slack_lifecycle_thread(
            conn,
            incident_id=iid,
            channel="#incidents",
            public_id=public_id,
            title="K4 lifecycle",
            commit=True,
        )

    assert len(ids) == len(LIFECYCLE_TEMPLATES)
    published = notify_once(notifier=fake, aggregate_id=str(iid), limit=20)
    assert published == len(LIFECYCLE_TEMPLATES)
    assert len(fake.posts) == len(LIFECYCLE_TEMPLATES)

    root = fake.posts[0]
    assert root["thread_ts"] is None
    root_ts = root["ts"]
    assert root_ts
    for reply in fake.posts[1:]:
        assert reply["thread_ts"] == root_ts

    kinds: list[str] = []
    for post in fake.posts:
        blob = str(post["blocks"]).lower().replace("\\n", "\n")
        text = post["text"].lower()
        if "*kind*\nbrief" in blob:
            kinds.append("brief")
        elif "*kind*\nevidence" in blob:
            kinds.append("evidence")
        elif "kind: status" in blob or " status —" in text:
            kinds.append("status")
        elif "*kind*\nrecovery" in blob or " recovery —" in text:
            kinds.append("recovery")
        elif "*kind*\npostmortem" in blob or " postmortem —" in text:
            kinds.append("postmortem")
        else:
            kinds.append("unknown")
    assert kinds == list(LIFECYCLE_TEMPLATES)

    for post in fake.posts:
        assert f"http://ui.test/incidents/{public_id}" in post["text"]

    with psycopg.connect(_dsn()) as conn:
        stored = get_slack_incident_thread(conn, incident_id=iid)
    assert stored == ("#incidents", root_ts)

    set_fake_slack_notifier(None)
