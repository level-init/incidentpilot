"""I3: Autonomy config Levels 1–3 — bad-deploy scored path → Level 2."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.autonomy import resolve_autonomy_level
from incidentpilot_shared.domain.commands import (
    create_incident_command,
    create_runbook_command,
    create_runbook_version_command,
    evaluate_policy_command,
    pin_runbook_version_command,
    propose_action_command,
    publish_runbook_version_command,
    upsert_autonomy_config_command,
)

psycopg = pytest.importorskip("psycopg")


def _dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "incidentpilot")
    password = os.environ.get("IP_APP_PASSWORD", "incidentpilot_app")
    return f"postgresql://ip_app:{password}@{host}:{port}/{db}"


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.autonomy_config LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


@pytest.mark.skipif(not _db_available(), reason="Postgres/I3 migration not reachable")
def test_bad_deploy_path_resolves_level2_require_approval(conn: object) -> None:
    match = resolve_autonomy_level(
        conn,
        service_key="checkout",
        action_type="ROLLBACK_DEPLOYMENT",
        environment="local",
        severity="SEV2",
    )
    assert match.autonomy_level == 2
    assert match.specificity >= 2  # at least service+action or seeded checkout row

    created = create_incident_command(
        conn,
        title="i3 bd scored",
        severity="SEV2",
        service_key="checkout",
        environment="local",
        commit=False,
    )
    rb = create_runbook_command(
        conn,
        key=f"i3.rb.{uuid.uuid4().hex[:8]}",
        title="I3 RB",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# i3",
        allowed_action_types=["ROLLBACK_DEPLOYMENT"],
        commit=False,
    )
    published = publish_runbook_version_command(
        conn, runbook_version_id=ver.runbook_version_id, commit=False
    )
    pin_runbook_version_command(
        conn,
        incident_id=created.incident_id,
        runbook_version_id=published.runbook_version_id,
        commit=False,
    )
    proposed = propose_action_command(
        conn,
        incident_id=created.incident_id,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters={"revision": "prev"},
        commit=False,
    )
    decision = evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        actor="system",
        commit=False,
    )
    assert decision.autonomy_level == 2
    assert decision.decision == "REQUIRE_APPROVAL"
    assert decision.autonomy_source == "config"


@pytest.mark.skipif(not _db_available(), reason="Postgres/I3 migration not reachable")
def test_level3_configurable_for_later(conn: object) -> None:
    upsert_autonomy_config_command(
        conn,
        service_key="checkout",
        action_type="ROLLBACK_DEPLOYMENT",
        environment="staging",
        severity=None,
        autonomy_level=3,
        notes="later Level 3 experiment — not production default",
        commit=False,
    )
    match = resolve_autonomy_level(
        conn,
        service_key="checkout",
        action_type="ROLLBACK_DEPLOYMENT",
        environment="staging",
    )
    assert match.autonomy_level == 3

    # Global / local bad-deploy remains Level 2 (more specific local seed or global).
    local = resolve_autonomy_level(
        conn,
        service_key="checkout",
        action_type="ROLLBACK_DEPLOYMENT",
        environment="local",
    )
    assert local.autonomy_level == 2


@pytest.mark.skipif(not _db_available(), reason="Postgres/I3 migration not reachable")
def test_specificity_prefers_narrower_row(conn: object) -> None:
    upsert_autonomy_config_command(
        conn,
        service_key="payments",
        action_type=None,
        environment=None,
        severity=None,
        autonomy_level=1,
        notes="payments observe-only",
        commit=False,
    )
    upsert_autonomy_config_command(
        conn,
        service_key="payments",
        action_type="RESTART_WORKLOAD",
        environment="local",
        severity=None,
        autonomy_level=2,
        notes="payments restart needs approval",
        commit=False,
    )
    match = resolve_autonomy_level(
        conn,
        service_key="payments",
        action_type="RESTART_WORKLOAD",
        environment="local",
    )
    assert match.autonomy_level == 2
    assert match.specificity >= 3
