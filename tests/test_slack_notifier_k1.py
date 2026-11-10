"""K1: outbound Slack notifier via outbox — BEST_EFFORT; cred off AI worker."""

from __future__ import annotations

import ast
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

from incidentpilot_adapters.slack import (  # noqa: E402
    FakeSlackNotifier,
    render_incident_brief,
    render_incident_update,
    set_fake_slack_notifier,
)
from incidentpilot_shared.slack_notify import (  # noqa: E402
    AI_FORBIDDEN_SLACK_ENV,
    SLACK_NOTIFY_EVENT,
    enqueue_slack_notify,
)
from incidentpilot_worker.slack_notifier import (  # noqa: E402
    incident_state,
    notify_once,
    outbox_row,
)

ROOT = Path(__file__).resolve().parents[1]


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.outbox_message LIMIT 1")
            return True
    except Exception:
        return False


def test_templates_brief_and_update() -> None:
    brief = render_incident_brief(
        public_id="INC-1",
        title="checkout 5xx",
        state="MITIGATING",
        summary="Rolling back payment deploy",
    )
    assert "INC-1" in brief.text
    assert "MITIGATING" in brief.text
    assert brief.blocks

    update = render_incident_update(
        public_id="INC-1",
        title="checkout 5xx",
        state="VALIDATING",
        note="Validation window started",
    )
    assert "VALIDATING" in update.text
    # K4: update template aliases status.
    assert "status" in update.text.lower() or any(
        "status" in str(b).lower() for b in update.blocks
    )


def test_ai_forbidden_slack_env_constant() -> None:
    assert "SLACK_BOT_TOKEN" in AI_FORBIDDEN_SLACK_ENV
    assert "SLACK_SIGNING_SECRET" in AI_FORBIDDEN_SLACK_ENV


def test_general_worker_modules_omit_slack_bot_token() -> None:
    """Cred must not appear in general / AI worker modules (notify process only)."""
    paths = [
        ROOT / "worker" / "incidentpilot_worker" / "worker_factory.py",
        ROOT / "worker" / "incidentpilot_worker" / "activities",
        ROOT / "adapters" / "incidentpilot_adapters" / "llm",
        ROOT / "shared" / "incidentpilot_shared" / "ai_tool_broker.py",
        ROOT / "shared" / "incidentpilot_shared" / "ai_tools.py",
    ]
    offenders: list[str] = []
    for path in paths:
        files = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for file in files:
            if "__pycache__" in file.parts:
                continue
            tree = ast.parse(file.read_text(encoding="utf-8"))
            names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    names.add(node.value)
                elif isinstance(node, ast.Name):
                    names.add(node.id)
            hits = names & AI_FORBIDDEN_SLACK_ENV
            if hits:
                offenders.append(f"{file.relative_to(ROOT)}:{sorted(hits)}")
    assert offenders == []


@pytest.fixture()
def mitigating_incident() -> Iterator[uuid.UUID]:
    if not _db_available():
        pytest.skip("Postgres not reachable")
    iid = uuid.uuid4()
    fake = FakeSlackNotifier()
    set_fake_slack_notifier(fake)
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (
                id, public_id, state, title, incident_revision
            ) VALUES (%s, %s, 'MITIGATING', 'K1 slack fault', 3)
            """,
            (str(iid), f"INC-K1-{iid.hex[:8]}"),
        )
        conn.commit()
    try:
        yield iid
    finally:
        set_fake_slack_notifier(None)


@pytest.mark.temporal_d6
@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_slack_failure_leaves_mitigating_intact(
    mitigating_incident: uuid.UUID,
) -> None:
    iid = mitigating_incident
    fake = FakeSlackNotifier(fail=True)
    set_fake_slack_notifier(fake)

    with psycopg.connect(_dsn()) as conn:
        mid = enqueue_slack_notify(
            conn,
            incident_id=iid,
            channel="#incidents",
            template="brief",
            public_id=f"INC-K1-{iid.hex[:8]}",
            title="K1 slack fault",
            state="MITIGATING",
            summary="rollback in progress",
        )
        conn.commit()

    published = notify_once(notifier=fake, aggregate_id=str(iid))
    assert published == 0
    assert incident_state(iid) == "MITIGATING"
    row = outbox_row(mid)
    assert row is not None
    assert row["status"] == "pending"
    assert row["event_type"] == SLACK_NOTIFY_EVENT
    assert row["last_error"]
    assert fake.posts == []


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_slack_success_publishes_without_domain_write(
    mitigating_incident: uuid.UUID,
) -> None:
    iid = mitigating_incident
    fake = FakeSlackNotifier(fail=False)
    set_fake_slack_notifier(fake)

    with psycopg.connect(_dsn()) as conn:
        mid = enqueue_slack_notify(
            conn,
            incident_id=iid,
            channel="#incidents",
            template="update",
            public_id=f"INC-K1-{iid.hex[:8]}",
            title="K1 slack fault",
            state="VALIDATING",
            note="entering validation",
        )
        # Domain stays MITIGATING even if payload says VALIDATING — notify is not a transition.
        conn.commit()

    published = notify_once(notifier=fake, aggregate_id=str(iid))
    assert published == 1
    assert incident_state(iid) == "MITIGATING"
    row = outbox_row(mid)
    assert row is not None
    assert row["status"] == "published"
    assert len(fake.posts) == 1
    assert fake.posts[0]["channel"] == "#incidents"
