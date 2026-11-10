"""J5: PAUSE_CONSUMER + REROUTE_TRAFFIC (PARTIAL includes observed_state)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from uuid import uuid4

import pytest

from incidentpilot_adapters.remediation import (
    RECONCILE_APPLIED,
    RECONCILE_NOT_APPLIED,
    RECONCILE_PARTIAL,
    BlindRetryForbidden,
    RemediationRequest,
    SimPauseConsumerAdapter,
    SimRerouteTrafficAdapter,
    SimTrafficWorld,
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
    service_key: str = "notification",
):
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'j5 traffic', 3)
            """,
            (str(incident_id), f"INC-J5-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"j5.rb.{uuid.uuid4().hex[:8]}",
        title="J5 RB",
        service_key=service_key,
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# j5",
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
        decided_by="harness:j5",
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


def test_pause_consumer_contract() -> None:
    world = SimTrafficWorld()
    world.seed_queue_backlog_fault()
    adapter = SimPauseConsumerAdapter(world)
    req = _req("PAUSE_CONSUMER", {"consumer": "notification-worker"})

    assert adapter.reconcile(req).reconciliation_state == RECONCILE_NOT_APPLIED
    result = adapter.execute(req)
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert world.paused["notification-worker"] is True
    assert result.adapter_result["observed_state"]["paused"] is True
    assert adapter.execute(req).skipped_execute is True
    assert world.pause_counts["notification-worker"] == 1


def test_reroute_partial_includes_observed_state() -> None:
    world = SimTrafficWorld()
    world.seed_queue_backlog_fault()
    world.set_route_partial("notification", {"primary": 40, "drain": 60})
    adapter = SimRerouteTrafficAdapter(world)
    req = _req(
        "REROUTE_TRAFFIC",
        {"service": "notification", "weights": {"primary": 0, "drain": 100}},
    )

    partial = adapter.reconcile(req)
    assert partial.reconciliation_state == RECONCILE_PARTIAL
    observed = partial.adapter_result["observed_state"]
    assert observed["service"] == "notification"
    assert observed["weights"] == {"drain": 60, "primary": 40}
    assert partial.adapter_result["desired_weights"] == {"drain": 100, "primary": 0}
    assert len(adapter.execute_calls) == 0

    # Full apply clears PARTIAL.
    applied = adapter.execute(req)
    assert applied.reconciliation_state == RECONCILE_APPLIED
    assert adapter.reconcile(req).reconciliation_state == RECONCILE_APPLIED
    assert world.routes["notification"] == {"drain": 100, "primary": 0}


def test_reroute_baseline_is_not_applied() -> None:
    world = SimTrafficWorld()
    world.seed_route("notification", {"primary": 100, "drain": 0})
    adapter = SimRerouteTrafficAdapter(world)
    req = _req(
        "REROUTE_TRAFFIC",
        {"service": "notification", "from": "primary", "target": "drain", "percent": 100},
    )
    assert adapter.reconcile(req).reconciliation_state == RECONCILE_NOT_APPLIED


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_pause_verify_reconcile_path(conn: object) -> None:
    params = {"consumer": "notification-worker"}
    proposed, attempt = _approved_attempt(
        conn, action_type="PAUSE_CONSUMER", parameters=params
    )
    world = SimTrafficWorld()
    world.seed_queue_backlog_fault()
    adapter = SimPauseConsumerAdapter(world)

    _verified, result = verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="PAUSE_CONSUMER",
    )
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert world.paused["notification-worker"] is True


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_reroute_partial_refuses_blind_retry(conn: object) -> None:
    params = {"service": "notification", "weights": {"primary": 0, "drain": 100}}
    proposed, attempt = _approved_attempt(
        conn, action_type="REROUTE_TRAFFIC", parameters=params
    )
    world = SimTrafficWorld()
    world.seed_queue_backlog_fault()
    world.set_route_partial("notification", {"primary": 25, "drain": 75})
    adapter = SimRerouteTrafficAdapter(world)

    with pytest.raises(BlindRetryForbidden, match="PARTIAL"):
        verify_reconcile_and_execute(
            conn,
            adapter,
            attempt_id=attempt.attempt_id,
            parameters=params,
            action_id=proposed.action_id,
            action_version=proposed.version,
            action_type="REROUTE_TRAFFIC",
        )
    assert len(adapter.execute_calls) == 0
    # observed_state still available from last reconcile
    last = adapter.reconcile_calls and adapter.reconcile(
        RemediationRequest(
            attempt_id=attempt.attempt_id,
            action_id=proposed.action_id,
            action_version=proposed.version,
            action_type="REROUTE_TRAFFIC",
            parameters=params,
        )
    )
    assert last.reconciliation_state == RECONCILE_PARTIAL
    assert "observed_state" in last.adapter_result
    assert last.adapter_result["observed_state"]["weights"] == {
        "drain": 75,
        "primary": 25,
    }


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_reroute_full_apply_path(conn: object) -> None:
    params = {"service": "notification", "weights": {"primary": 0, "drain": 100}}
    proposed, attempt = _approved_attempt(
        conn, action_type="REROUTE_TRAFFIC", parameters=params
    )
    world = SimTrafficWorld()
    world.seed_queue_backlog_fault()
    adapter = SimRerouteTrafficAdapter(world)

    _verified, result = verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="REROUTE_TRAFFIC",
    )
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert world.routes["notification"] == {"drain": 100, "primary": 0}
