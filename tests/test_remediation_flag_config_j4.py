"""J4: feature-flag disable/restore + config restore against sim faults."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from uuid import uuid4

import pytest

from incidentpilot_adapters.remediation import (
    RECONCILE_APPLIED,
    RECONCILE_NOT_APPLIED,
    BlindRetryForbidden,
    LostAckError,
    RemediationRequest,
    SimConfigRestoreAdapter,
    SimFeatureFlagAdapter,
    SimFlagConfigWorld,
)
from incidentpilot_remediation.execute import verify_reconcile_and_execute
from incidentpilot_shared.domain.commands import (
    create_approval_command,
    create_runbook_command,
    create_runbook_version_command,
    decide_approval_command,
    evaluate_policy_command,
    pin_runbook_version_command,
    propose_action_command,
    publish_runbook_version_command,
    reserve_execution_attempt_command,
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
                cur.execute("SELECT 1 FROM domain.execution_attempt LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def _approved_attempt(
    conn: object,
    *,
    action_type: str,
    parameters: dict,
):
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'j4 flag-config', 3)
            """,
            (str(incident_id), f"INC-J4-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"j4.rb.{uuid.uuid4().hex[:8]}",
        title="J4 RB",
        service_key="auth",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# j4",
        allowed_action_types=[action_type],
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
    proposed = propose_action_command(
        conn,
        incident_id=incident_id,
        action_type=action_type,
        parameters=parameters,
        commit=False,
    )
    evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        autonomy_level=2,
        actor="system",
        commit=False,
    )
    create_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        commit=False,
    )
    decide_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        status="APPROVED",
        decided_by="harness:j4",
        commit=False,
    )
    attempt = reserve_execution_attempt_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        commit=False,
    )
    return proposed, attempt


def _req(action_type: str, parameters: dict) -> RemediationRequest:
    return RemediationRequest(
        attempt_id=uuid4(),
        action_id=uuid4(),
        action_version=1,
        action_type=action_type,
        parameters=parameters,
    )


def test_scenario_smoke_disable_bad_flag() -> None:
    world = SimFlagConfigWorld()
    world.seed_bad_flag_fault()
    assert world.flags["auth:strict_jwt"] is True
    adapter = SimFeatureFlagAdapter(world)
    req = _req(
        "DISABLE_FEATURE_FLAG",
        {"flag": "strict_jwt", "service": "auth"},
    )
    assert adapter.reconcile(req).reconciliation_state == RECONCILE_NOT_APPLIED
    result = adapter.execute(req)
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert world.flags["auth:strict_jwt"] is False
    assert adapter.reconcile(req).reconciliation_state == RECONCILE_APPLIED
    assert adapter.execute(req).skipped_execute is True
    assert world.flag_apply_counts["auth:strict_jwt"] == 1


def test_scenario_smoke_restore_flag_and_configs() -> None:
    world = SimFlagConfigWorld()
    world.seed_bad_flag_fault()
    world.seed_bad_config_faults()
    flag_adapter = SimFeatureFlagAdapter(world)
    config_adapter = SimConfigRestoreAdapter(world)

    restore_flag = _req(
        "RESTORE_FEATURE_FLAG",
        {"flag": "strict_jwt", "service": "auth", "value": False},
    )
    assert flag_adapter.execute(restore_flag).ok is True
    assert world.flags["auth:strict_jwt"] is False

    skew = _req(
        "RESTORE_CONFIG",
        {"key": "jwt_skew_seconds", "service": "auth", "value": 30},
    )
    pool = _req(
        "RESTORE_CONFIG",
        {"key": "pool_size", "service": "inventory", "value": 20},
    )
    assert config_adapter.reconcile(skew).reconciliation_state == RECONCILE_NOT_APPLIED
    assert config_adapter.execute(skew).reconciliation_state == RECONCILE_APPLIED
    assert world.configs["auth:jwt_skew_seconds"] == 30
    assert config_adapter.execute(pool).reconciliation_state == RECONCILE_APPLIED
    assert world.configs["inventory:pool_size"] == 20


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_disable_flag_verify_reconcile_path(conn: object) -> None:
    params = {"flag": "strict_jwt", "service": "auth"}
    proposed, attempt = _approved_attempt(
        conn, action_type="DISABLE_FEATURE_FLAG", parameters=params
    )
    world = SimFlagConfigWorld()
    world.seed_bad_flag_fault()
    adapter = SimFeatureFlagAdapter(world)

    _verified, result = verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="DISABLE_FEATURE_FLAG",
    )
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert world.flags["auth:strict_jwt"] is False


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_restore_config_lost_ack_no_double_apply(conn: object) -> None:
    params = {"key": "pool_size", "service": "inventory", "value": 20}
    proposed, attempt = _approved_attempt(
        conn, action_type="RESTORE_CONFIG", parameters=params
    )
    world = SimFlagConfigWorld()
    world.seed_bad_config_faults()
    world.lose_ack_once.add("inventory:pool_size")
    adapter = SimConfigRestoreAdapter(world)

    with pytest.raises(LostAckError, match="lost ACK"):
        verify_reconcile_and_execute(
            conn,
            adapter,
            attempt_id=attempt.attempt_id,
            parameters=params,
            action_id=proposed.action_id,
            action_version=proposed.version,
            action_type="RESTORE_CONFIG",
        )
    assert world.configs["inventory:pool_size"] == 20
    assert world.config_apply_counts["inventory:pool_size"] == 1

    _verified, result = verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="RESTORE_CONFIG",
    )
    assert result.skipped_execute is True
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert world.config_apply_counts["inventory:pool_size"] == 1
    assert len(adapter.execute_calls) == 1


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_flag_unknown_refuses_blind_retry(conn: object) -> None:
    params = {"flag": "strict_jwt", "service": "auth"}
    proposed, attempt = _approved_attempt(
        conn, action_type="DISABLE_FEATURE_FLAG", parameters=params
    )
    world = SimFlagConfigWorld()
    world.seed_bad_flag_fault()
    world.force_unknown.add("auth:strict_jwt")
    adapter = SimFeatureFlagAdapter(world)

    with pytest.raises(BlindRetryForbidden, match="UNKNOWN"):
        verify_reconcile_and_execute(
            conn,
            adapter,
            attempt_id=attempt.attempt_id,
            parameters=params,
            action_id=proposed.action_id,
            action_version=proposed.version,
            action_type="DISABLE_FEATURE_FLAG",
        )
    assert len(adapter.execute_calls) == 0
    assert world.flags["auth:strict_jwt"] is True
