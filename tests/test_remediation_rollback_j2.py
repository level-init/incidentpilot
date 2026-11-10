"""J2: ROLLBACK_DEPLOYMENT + reconcile (clear bad rev; lost-ACK no double-apply)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_adapters.remediation import (
    RECONCILE_APPLIED,
    RECONCILE_NOT_APPLIED,
    RECONCILE_PARTIAL,
    RECONCILE_UNKNOWN,
    BlindRetryForbidden,
    LostAckError,
    SimDeploymentWorld,
    SimRollbackAdapter,
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


def _approved_rollback_attempt(
    conn: object,
    *,
    parameters: dict | None = None,
):
    params = parameters or {"revision": "prev", "deployment": "checkout"}
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'j2 rollback', 3)
            """,
            (str(incident_id), f"INC-J2-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"j2.rb.{uuid.uuid4().hex[:8]}",
        title="J2 RB",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# j2",
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
    proposed = propose_action_command(
        conn,
        incident_id=incident_id,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters=params,
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
        decided_by="harness:j2",
        commit=False,
    )
    attempt = reserve_execution_attempt_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        commit=False,
    )
    return proposed, attempt, params


def test_sim_reconcile_states_without_db() -> None:
    world = SimDeploymentWorld()
    world.seed("checkout", "bad")
    adapter = SimRollbackAdapter(world)
    from uuid import uuid4

    req_kwargs = dict(
        attempt_id=uuid4(),
        action_id=uuid4(),
        action_version=1,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters={"revision": "prev", "deployment": "checkout"},
    )
    from incidentpilot_adapters.remediation import RemediationRequest

    req = RemediationRequest(**req_kwargs)
    assert adapter.reconcile(req).reconciliation_state == RECONCILE_NOT_APPLIED

    world.force_unknown.add("checkout")
    assert adapter.reconcile(req).reconciliation_state == RECONCILE_UNKNOWN
    world.force_unknown.clear()
    world.force_partial.add("checkout")
    assert adapter.reconcile(req).reconciliation_state == RECONCILE_PARTIAL
    world.force_partial.clear()

    adapter.execute(req)
    assert adapter.reconcile(req).reconciliation_state == RECONCILE_APPLIED
    assert world.observe("checkout") == "prev"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_rollback_clears_bad_revision(conn: object) -> None:
    proposed, attempt, params = _approved_rollback_attempt(conn)
    world = SimDeploymentWorld()
    world.seed(params["deployment"], "bad")
    adapter = SimRollbackAdapter(world)

    verified, result = verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="ROLLBACK_DEPLOYMENT",
    )
    assert verified.parameters == params
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert result.skipped_execute is False
    assert world.observe("checkout") == "prev"
    assert world.apply_counts["checkout"] == 1
    assert len(adapter.execute_calls) == 1


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_retry_after_lost_ack_does_not_double_apply(conn: object) -> None:
    proposed, attempt, params = _approved_rollback_attempt(conn)
    world = SimDeploymentWorld()
    world.seed(params["deployment"], "bad")
    world.lose_ack_once.add(params["deployment"])
    adapter = SimRollbackAdapter(world)

    with pytest.raises(LostAckError, match="lost ACK"):
        verify_reconcile_and_execute(
            conn,
            adapter,
            attempt_id=attempt.attempt_id,
            parameters=params,
            action_id=proposed.action_id,
            action_version=proposed.version,
            action_type="ROLLBACK_DEPLOYMENT",
        )
    # Mutate landed despite lost ACK.
    assert world.observe("checkout") == "prev"
    assert world.apply_counts["checkout"] == 1

    verified, result = verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="ROLLBACK_DEPLOYMENT",
    )
    assert verified.attempt_id == attempt.attempt_id
    assert result.reconciliation_state == RECONCILE_APPLIED
    assert result.skipped_execute is True
    assert world.apply_counts["checkout"] == 1
    assert len(adapter.execute_calls) == 1  # retry never re-executed


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_unknown_reconcile_refuses_blind_retry(conn: object) -> None:
    proposed, attempt, params = _approved_rollback_attempt(conn)
    world = SimDeploymentWorld()
    world.seed(params["deployment"], "bad")
    world.force_unknown.add(params["deployment"])
    adapter = SimRollbackAdapter(world)

    with pytest.raises(BlindRetryForbidden, match="UNKNOWN"):
        verify_reconcile_and_execute(
            conn,
            adapter,
            attempt_id=attempt.attempt_id,
            parameters=params,
            action_id=proposed.action_id,
            action_version=proposed.version,
            action_type="ROLLBACK_DEPLOYMENT",
        )
    assert len(adapter.execute_calls) == 0
    assert world.observe("checkout") == "bad"
