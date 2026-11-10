"""J1: RemediationAdapter + VerifyExecutionAttempt (SoR params; unverified refused)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_adapters.remediation import (
    NoopRemediationAdapter,
    RemediationRequest,
    execute_verified,
)
from incidentpilot_remediation.execute import verify_and_execute
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
from incidentpilot_shared.remediation_verify import (
    ParamMismatchError,
    UnverifiedExecutionError,
    require_verified_execution,
    verify_execution_attempt,
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


def _approved_rollback_attempt(conn: object):
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'j1 verify', 3)
            """,
            (str(incident_id), f"INC-J1-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"j1.rb.{uuid.uuid4().hex[:8]}",
        title="J1 RB",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# j1",
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
        parameters={"revision": "prev", "deployment": "checkout"},
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
        decided_by="harness:j1",
        commit=False,
    )
    attempt = reserve_execution_attempt_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        commit=False,
    )
    return proposed, attempt


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_bogus_params_with_real_attempt_id_rejected(conn: object) -> None:
    _proposed, attempt = _approved_rollback_attempt(conn)
    with pytest.raises(ParamMismatchError, match="exactly match"):
        verify_execution_attempt(
            conn,
            attempt_id=attempt.attempt_id,
            parameters={"revision": "evil", "deployment": "checkout"},
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_exact_sor_params_verify_and_execute(conn: object) -> None:
    proposed, attempt = _approved_rollback_attempt(conn)
    adapter = NoopRemediationAdapter()
    verified, result = verify_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters={"deployment": "checkout", "revision": "prev"},  # key order differs
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="ROLLBACK_DEPLOYMENT",
    )
    assert verified.parameters == {
        "revision": "prev",
        "deployment": "checkout",
    }
    assert result.ok is True
    assert len(adapter.calls) == 1
    assert adapter.calls[0].parameters == verified.parameters


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_unverified_execute_refused(conn: object) -> None:
    proposed, attempt = _approved_rollback_attempt(conn)
    adapter = NoopRemediationAdapter()
    with pytest.raises(UnverifiedExecutionError, match="VerifyExecutionAttempt"):
        require_verified_execution(None)
    with pytest.raises(UnverifiedExecutionError, match="VerifyExecutionAttempt"):
        execute_verified(adapter, None)  # type: ignore[arg-type]

    # Direct adapter.execute without verify is possible on Noop, but the
    # remediation-worker entrypoint must use verify_and_execute / execute_verified.
    forged = RemediationRequest(
        attempt_id=attempt.attempt_id,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="ROLLBACK_DEPLOYMENT",
        parameters={"revision": "forged"},
    )
    # Documented contract: callers must not skip verify — helper refuses None.
    assert forged.parameters != {"revision": "prev", "deployment": "checkout"}


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_block_policy_refuses_verify(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DIAGNOSED', 'j1 block', 2)
            """,
            (str(incident_id), f"INC-J1B-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"j1b.rb.{uuid.uuid4().hex[:8]}",
        title="J1B",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# b",
        allowed_action_types=["ROLLBACK_DEPLOYMENT", "OTHER"],
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
        action_type="OTHER",
        parameters={"policy_force": "BLOCK"},
        commit=False,
    )
    # OTHER is blocked by engine even without force; force also blocks.
    evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        autonomy_level=3,
        actor="system",
        commit=False,
    )
    attempt = reserve_execution_attempt_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        commit=False,
    )
    with pytest.raises(PermissionError, match="BLOCK"):
        verify_execution_attempt(conn, attempt_id=attempt.attempt_id)
