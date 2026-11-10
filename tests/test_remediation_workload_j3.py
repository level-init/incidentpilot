"""J3: RESTART_WORKLOAD + SCALE_WORKLOAD under RemediationAdapter contract."""

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
    SimRestartAdapter,
    SimScaleAdapter,
    SimWorkloadWorld,
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
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'j3 workload', 3)
            """,
            (str(incident_id), f"INC-J3-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"j3.rb.{uuid.uuid4().hex[:8]}",
        title="J3 RB",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# j3",
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
        decided_by="harness:j3",
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


def test_restart_contract_reconcile_and_idempotent_execute() -> None:
    world = SimWorkloadWorld()
    world.seed("checkout-api", generation=2, replicas=2)
    adapter = SimRestartAdapter(world)
    req = _req("RESTART_WORKLOAD", {"workload": "checkout-api"})

    assert adapter.reconcile(req).reconciliation_state == RECONCILE_NOT_APPLIED
    result = adapter.execute(req)
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert world.generations["checkout-api"] == 3
    assert world.restart_counts["checkout-api"] == 1
    assert adapter.reconcile(req).reconciliation_state == RECONCILE_APPLIED

    again = adapter.execute(req)
    assert again.skipped_execute is True
    assert world.restart_counts["checkout-api"] == 1


def test_scale_contract_reconcile_and_idempotent_execute() -> None:
    world = SimWorkloadWorld()
    world.seed("checkout-api", generation=1, replicas=2)
    adapter = SimScaleAdapter(world)
    req = _req("SCALE_WORKLOAD", {"workload": "checkout-api", "replicas": 5})

    assert adapter.reconcile(req).reconciliation_state == RECONCILE_NOT_APPLIED
    result = adapter.execute(req)
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert world.replicas["checkout-api"] == 5
    assert world.scale_counts["checkout-api"] == 1
    assert adapter.reconcile(req).reconciliation_state == RECONCILE_APPLIED

    again = adapter.execute(req)
    assert again.skipped_execute is True
    assert world.scale_counts["checkout-api"] == 1


def test_adapters_reject_wrong_action_type() -> None:
    world = SimWorkloadWorld()
    world.seed("x")
    restart = SimRestartAdapter(world)
    scale = SimScaleAdapter(world)
    bad_restart = _req("SCALE_WORKLOAD", {"workload": "x", "replicas": 1})
    bad_scale = _req("RESTART_WORKLOAD", {"workload": "x"})
    assert restart.execute(bad_restart).error_summary == "unsupported_action_type"
    assert scale.execute(bad_scale).error_summary == "unsupported_action_type"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_restart_verify_reconcile_path(conn: object) -> None:
    params = {"workload": "checkout-api"}
    proposed, attempt = _approved_attempt(
        conn, action_type="RESTART_WORKLOAD", parameters=params
    )
    world = SimWorkloadWorld()
    world.seed("checkout-api", generation=1)
    adapter = SimRestartAdapter(world)

    _verified, result = verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="RESTART_WORKLOAD",
    )
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert world.generations["checkout-api"] == 2
    assert world.restart_counts["checkout-api"] == 1


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_scale_verify_reconcile_path(conn: object) -> None:
    params = {"workload": "checkout-api", "replicas": 4}
    proposed, attempt = _approved_attempt(
        conn, action_type="SCALE_WORKLOAD", parameters=params
    )
    world = SimWorkloadWorld()
    world.seed("checkout-api", replicas=1)
    adapter = SimScaleAdapter(world)

    _verified, result = verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="SCALE_WORKLOAD",
    )
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert world.replicas["checkout-api"] == 4
    assert world.scale_counts["checkout-api"] == 1


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_scale_lost_ack_no_double_apply(conn: object) -> None:
    params = {"workload": "checkout-api", "replicas": 3}
    proposed, attempt = _approved_attempt(
        conn, action_type="SCALE_WORKLOAD", parameters=params
    )
    world = SimWorkloadWorld()
    world.seed("checkout-api", replicas=1)
    world.lose_ack_once.add("checkout-api")
    adapter = SimScaleAdapter(world)

    with pytest.raises(LostAckError, match="lost ACK"):
        verify_reconcile_and_execute(
            conn,
            adapter,
            attempt_id=attempt.attempt_id,
            parameters=params,
            action_id=proposed.action_id,
            action_version=proposed.version,
            action_type="SCALE_WORKLOAD",
        )
    assert world.replicas["checkout-api"] == 3
    assert world.scale_counts["checkout-api"] == 1

    _verified, result = verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="SCALE_WORKLOAD",
    )
    assert result.skipped_execute is True
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert world.scale_counts["checkout-api"] == 1
    assert len(adapter.execute_calls) == 1


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_restart_unknown_refuses_blind_retry(conn: object) -> None:
    params = {"workload": "checkout-api"}
    proposed, attempt = _approved_attempt(
        conn, action_type="RESTART_WORKLOAD", parameters=params
    )
    world = SimWorkloadWorld()
    world.seed("checkout-api")
    world.force_unknown.add("checkout-api")
    adapter = SimRestartAdapter(world)

    with pytest.raises(BlindRetryForbidden, match="UNKNOWN"):
        verify_reconcile_and_execute(
            conn,
            adapter,
            attempt_id=attempt.attempt_id,
            parameters=params,
            action_id=proposed.action_id,
            action_version=proposed.version,
            action_type="RESTART_WORKLOAD",
        )
    assert len(adapter.execute_calls) == 0
