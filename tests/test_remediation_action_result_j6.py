"""J6: RemediationResult → Producer → ACTION_RESULT Evidence (adapters cannot write)."""

from __future__ import annotations

import ast
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from incidentpilot_adapters.remediation import (
    LostAckError,
    SimDeploymentWorld,
    SimRollbackAdapter,
)
from incidentpilot_remediation.execute import verify_reconcile_and_execute
from incidentpilot_shared.domain.commands import (
    append_action_result_evidence_command,
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
from incidentpilot_shared.evidence_producers import (
    EvidenceProducerDenied,
    is_registered_evidence_producer,
)

psycopg = pytest.importorskip("psycopg")

ROOT = Path(__file__).resolve().parents[1]


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


def _approved_rollback(conn: object):
    params = {"revision": "prev", "deployment": "checkout"}
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'AWAITING_APPROVAL', 'j6 action result', 3)
            """,
            (str(incident_id), f"INC-J6-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"j6.rb.{uuid.uuid4().hex[:8]}",
        title="J6 RB",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# j6",
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
        decided_by="harness:j6",
        commit=False,
    )
    attempt = reserve_execution_attempt_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        commit=False,
    )
    return incident_id, proposed, attempt, params


def test_remediation_worker_producer_registered() -> None:
    assert is_registered_evidence_producer("remediation_worker")


def test_remediation_adapters_cannot_write_evidence() -> None:
    remediation_root = ROOT / "adapters" / "incidentpilot_adapters" / "remediation"
    offenders: list[str] = []
    for path in remediation_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "append_evidence" in text or "append_action_result_evidence" in text:
            offenders.append(f"{path.relative_to(ROOT)}:append_evidence")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.endswith("domain.commands") or node.module.endswith(
                    ".commands"
                ):
                    # allow typing-only? none expected in remediation adapters
                    offenders.append(f"{path.relative_to(ROOT)}:import {node.module}")
    assert offenders == []


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_action_result_evidence_after_execute(conn: object) -> None:
    incident_id, proposed, attempt, params = _approved_rollback(conn)
    world = SimDeploymentWorld()
    world.seed("checkout", "bad")
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
    assert result.ok is True
    assert verified.incident_id == incident_id

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kind, producer, provenance->>'layer', fingerprint, summary
            FROM domain.evidence
            WHERE incident_id = %s AND kind = 'ACTION_RESULT'
            """,
            (str(incident_id),),
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    kind, producer, layer, fingerprint, summary = rows[0]
    assert kind == "ACTION_RESULT"
    assert producer == "remediation_worker"
    assert layer == "ACTION_OBSERVATION"
    assert fingerprint == f"remediation_worker:attempt:{attempt.attempt_id}"
    assert summary


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_action_result_idempotent_after_lost_ack(conn: object) -> None:
    incident_id, proposed, attempt, params = _approved_rollback(conn)
    world = SimDeploymentWorld()
    world.seed("checkout", "bad")
    world.lose_ack_once.add("checkout")
    adapter = SimRollbackAdapter(world)

    with pytest.raises(LostAckError):
        verify_reconcile_and_execute(
            conn,
            adapter,
            attempt_id=attempt.attempt_id,
            parameters=params,
            action_id=proposed.action_id,
            action_version=proposed.version,
            action_type="ROLLBACK_DEPLOYMENT",
        )
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM domain.evidence
            WHERE incident_id = %s AND kind = 'ACTION_RESULT'
            """,
            (str(incident_id),),
        )
        assert cur.fetchone()[0] == 0

    verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="ROLLBACK_DEPLOYMENT",
    )
    # Second call (already APPLIED) is idempotent on fingerprint.
    verify_reconcile_and_execute(
        conn,
        adapter,
        attempt_id=attempt.attempt_id,
        parameters=params,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="ROLLBACK_DEPLOYMENT",
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*), min(fingerprint)
            FROM domain.evidence
            WHERE incident_id = %s AND kind = 'ACTION_RESULT'
            """,
            (str(incident_id),),
        )
        count, fingerprint = cur.fetchone()
    assert count == 1
    assert fingerprint == f"remediation_worker:attempt:{attempt.attempt_id}"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_unregistered_producer_cannot_spoof_action_result(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'MITIGATING', 'j6 deny', 1)
            """,
            (str(incident_id), f"INC-J6D-{uuid.uuid4().hex[:8]}"),
        )
    with pytest.raises(EvidenceProducerDenied):
        # Direct command always uses remediation_worker; spoof via append_evidence.
        from incidentpilot_shared.domain.commands import append_evidence_command

        append_evidence_command(
            conn,
            incident_id=incident_id,
            kind="ACTION_RESULT",
            fingerprint="spoof",
            summary="nope",
            producer="sim_rollback",
            commit=False,
        )
    # Sanity: the real SYSTEM helper is allowed.
    ev = append_action_result_evidence_command(
        conn,
        incident_id=incident_id,
        attempt_id=uuid.uuid4(),
        action_id=uuid.uuid4(),
        action_version=1,
        action_type="ROLLBACK_DEPLOYMENT",
        summary="ok",
        commit=False,
    )
    assert ev.inserted is True
