"""I7: Admin policy versioning — new versions; past PolicyDecision unchanged."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import (
    create_runbook_command,
    create_runbook_version_command,
    evaluate_policy_command,
    list_policy_definitions,
    pin_runbook_version_command,
    propose_action_command,
    publish_policy_version_command,
    publish_runbook_version_command,
)

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402


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
                cur.execute(
                    """
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'policy_definition_forbid_update'
                    """
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def _propose_rollback(conn: object):
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DIAGNOSED', 'i7 policy', 2)
            """,
            (str(incident_id), f"INC-I7-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"i7.rb.{uuid.uuid4().hex[:8]}",
        title="I7 RB",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# i7",
        allowed_action_types=["ROLLBACK_DEPLOYMENT"],
        commit=False,
    )
    published = publish_runbook_version_command(
        conn, runbook_version_id=ver.runbook_version_id, commit=False
    )
    pin_runbook_version_command(
        conn,
        incident_id=incident_id,
        runbook_version_id=published.runbook_version_id,
        commit=False,
    )
    return propose_action_command(
        conn,
        incident_id=incident_id,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters={"revision": "prev"},
        commit=False,
    )


@pytest.mark.skipif(not _db_available(), reason="Postgres/I7 migration not reachable")
def test_publish_creates_new_version_and_stamps_decision(conn: object) -> None:
    published = publish_policy_version_command(
        conn,
        policy_key="default",
        body={
            "engine": "policy_engine.v1",
            "block_action_types": ["OTHER"],
            "level3_autonomous_action_types": ["ROLLBACK_DEPLOYMENT"],
        },
        notes="i7 test v-next",
        created_by="admin-test",
        activate=True,
        commit=False,
    )
    assert published.version >= 2
    assert published.version_label == f"v{published.version}"
    assert published.active is True

    proposed = _propose_rollback(conn)
    decision = evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    assert decision.policy_key == "default"
    assert decision.policy_version == published.version_label

    history = list_policy_definitions(conn, policy_key="default")
    assert any(h.version == published.version and h.active for h in history)
    assert any(h.version == 1 for h in history)


@pytest.mark.skipif(not _db_available(), reason="Postgres/I7 migration not reachable")
def test_old_policy_decision_unchanged_when_new_version_published(conn: object) -> None:
    proposed = _propose_rollback(conn)
    first = evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    old_version = first.policy_version

    publish_policy_version_command(
        conn,
        policy_key="default",
        body={"block_action_types": ["OTHER", "SCALE_WORKLOAD"]},
        notes="later policy",
        created_by="admin-test",
        activate=True,
        commit=False,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT policy_key, policy_version, decision, reason
            FROM domain.policy_decision WHERE id = %s
            """,
            (str(first.policy_decision_id),),
        )
        key, version, decision, reason = cur.fetchone()
    assert key == "default"
    assert version == old_version
    assert decision == "REQUIRE_APPROVAL"
    assert reason  # unchanged snapshot

    with conn.cursor() as cur:
        with pytest.raises(Exception, match="immutable"):
            cur.execute(
                """
                UPDATE domain.policy_decision
                SET policy_version = 'mutated'
                WHERE id = %s
                """,
                (str(first.policy_decision_id),),
            )


@pytest.mark.skipif(not _db_available(), reason="Postgres/I7 migration not reachable")
def test_policy_definition_rows_immutable(conn: object) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM domain.policy_definition
            WHERE policy_key = 'default' AND version = 1
            """
        )
        row = cur.fetchone()
        assert row is not None
        with pytest.raises(Exception, match="immutable|permission denied"):
            cur.execute(
                """
                UPDATE domain.policy_definition
                SET notes = 'mutated'
                WHERE id = %s
                """,
                (str(row[0]),),
            )


@pytest.mark.skipif(not _db_available(), reason="Postgres/I7 migration not reachable")
def test_admin_api_publish_and_history(conn: object) -> None:
    # Commit a unique body via API so OpenAPI path is exercised.
    with TestClient(app) as client:
        denied = client.post(
            "/policies/default/versions",
            headers={"Authorization": "Bearer local-dev"},
            json={"body": {"block_action_types": ["OTHER"]}, "notes": "nope"},
        )
        assert denied.status_code == 403, denied.text

        res = client.post(
            "/policies/default/versions",
            headers={"Authorization": "Bearer local-dev-admin"},
            json={
                "body": {
                    "engine": "policy_engine.v1",
                    "block_action_types": ["OTHER"],
                    "level3_autonomous_action_types": [],
                },
                "notes": "api publish",
                "activate": True,
            },
        )
        assert res.status_code == 201, res.text
        created = res.json()
        assert created["active"] is True
        assert created["created_by"] == "user_local_admin"

        hist = client.get(
            "/policies/default/versions",
            headers={"Authorization": "Bearer local-dev"},
        )
        assert hist.status_code == 200, hist.text
        labels = [row["version_label"] for row in hist.json()]
        assert created["version_label"] in labels

        # Reactivate v1 explicitly.
        act = client.post(
            "/policies/default/versions/1/activate",
            headers={"Authorization": "Bearer local-dev-admin"},
        )
        assert act.status_code == 200, act.text
        assert act.json()["version"] == 1
