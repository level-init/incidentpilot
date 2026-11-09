"""I2: Deterministic policy engine + immutable PolicyDecision."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.ai_tools import (
    AI_SANDBOX_IDENTITY,
    DENIED_TOOL_NAMES,
    ToolDeniedError,
    default_ai_tool_registry,
)
from incidentpilot_shared.domain.commands import (
    PolicyActorDenied,
    PolicyDecisionExists,
    create_runbook_command,
    create_runbook_version_command,
    evaluate_policy_command,
    pin_runbook_version_command,
    propose_action_command,
    publish_runbook_version_command,
)
from incidentpilot_shared.processors.policy import (
    assert_not_blocked,
    evaluate_policy,
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
                cur.execute(
                    """
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'policy_decision_forbid_update'
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


def test_engine_level2_requires_approval() -> None:
    v = evaluate_policy(action_type="ROLLBACK_DEPLOYMENT", autonomy_level=2)
    assert v.decision == "REQUIRE_APPROVAL"


def test_engine_block_never_executes() -> None:
    v = evaluate_policy(action_type="OTHER", autonomy_level=3)
    assert v.decision == "BLOCK"
    with pytest.raises(PermissionError, match="BLOCK"):
        assert_not_blocked(v.decision)
    assert_not_blocked("ALLOW_AUTONOMOUS")


def test_ai_cannot_call_policy_eval_tool() -> None:
    registry = default_ai_tool_registry()
    assert "POLICY_EVAL" in DENIED_TOOL_NAMES
    assert "policy_eval" in DENIED_TOOL_NAMES
    with pytest.raises(ToolDeniedError, match=AI_SANDBOX_IDENTITY):
        registry.require_allowed("POLICY_EVAL")


def _propose_rollback(conn: object, *, parameters: dict | None = None):
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DIAGNOSED', 'i2 policy', 2)
            """,
            (str(incident_id), f"INC-I2-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"i2.rb.{uuid.uuid4().hex[:8]}",
        title="I2 RB",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# i2",
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
        parameters=parameters or {"revision": "prev"},
        commit=False,
    )


@pytest.mark.skipif(not _db_available(), reason="Postgres/I2 migration not reachable")
def test_system_persists_immutable_decision(conn: object) -> None:
    proposed = _propose_rollback(conn)
    result = evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    assert result.decision == "REQUIRE_APPROVAL"
    assert result.action_status == "POLICY_EVALUATED"

    with pytest.raises(PolicyDecisionExists):
        evaluate_policy_command(
            conn,
            action_id=proposed.action_id,
            autonomy_level=2,
            actor="system",
            commit=False,
        )

    with conn.cursor() as cur:
        with pytest.raises(Exception, match="immutable"):
            cur.execute(
                """
                UPDATE domain.policy_decision
                SET reason = 'mutated'
                WHERE id = %s
                """,
                (str(result.policy_decision_id),),
            )


@pytest.mark.skipif(not _db_available(), reason="Postgres/I2 migration not reachable")
def test_block_sets_action_blocked_and_ai_denied(conn: object) -> None:
    proposed = _propose_rollback(conn, parameters={"policy_force": "BLOCK"})
    with pytest.raises(PolicyActorDenied):
        evaluate_policy_command(
            conn,
            action_id=proposed.action_id,
            actor=AI_SANDBOX_IDENTITY,
            commit=False,
        )
    result = evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        actor="system",
        commit=False,
    )
    assert result.decision == "BLOCK"
    assert result.action_status == "BLOCKED"
    with pytest.raises(PermissionError, match="BLOCK"):
        assert_not_blocked(result.decision)
