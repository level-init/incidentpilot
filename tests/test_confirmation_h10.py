"""H10: Confirmation rules by hypothesis class — RECOVERED alone insufficient."""

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
    CausedByActorDenied,
    ConfirmActorDenied,
    ConfirmationRulesNotMet,
    append_evidence_command,
    confirm_hypothesis_command,
    create_incident_command,
    link_evidence_relation_command,
    propose_hypothesis_command,
)
from incidentpilot_shared.processors.confirmation import (
    ConfirmationSignals,
    evaluate_confirmation_rules,
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
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'evidence_relation_type_check'
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


def test_recovered_alone_insufficient_deploy_class() -> None:
    decision = evaluate_confirmation_rules(
        ConfirmationSignals(
            hypothesis_status="LEADING",
            hypothesis_class="bad_deployment",
            validation_recovered=True,
            has_change_evidence=False,
            has_action_result_evidence=False,
            cited_evidence_count=1,
        )
    )
    assert decision.confirm is False
    assert "RECOVERED alone" in decision.reason or "CHANGE" in decision.reason


def test_deploy_class_requires_change_and_action_result() -> None:
    partial = evaluate_confirmation_rules(
        ConfirmationSignals(
            hypothesis_status="LEADING",
            hypothesis_class="bad_deployment",
            validation_recovered=True,
            has_change_evidence=True,
            has_action_result_evidence=False,
            cited_evidence_count=1,
        )
    )
    assert partial.confirm is False

    ok = evaluate_confirmation_rules(
        ConfirmationSignals(
            hypothesis_status="LEADING",
            hypothesis_class="bad_deployment",
            validation_recovered=True,
            has_change_evidence=True,
            has_action_result_evidence=True,
            cited_evidence_count=1,
        )
    )
    assert ok.confirm is True
    assert ok.write_caused_by is True


def test_ai_tools_cannot_confirm_or_write_caused_by() -> None:
    registry = default_ai_tool_registry()
    for name in (
        "confirm_hypothesis",
        "hypothesis_confirm",
        "write_caused_by",
        "caused_by",
        "set_caused_by",
    ):
        assert name in DENIED_TOOL_NAMES
        with pytest.raises(ToolDeniedError, match=AI_SANDBOX_IDENTITY):
            registry.require_allowed(name)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_human_cannot_write_caused_by_directly(conn: object) -> None:
    created = create_incident_command(conn, title="h10 caused_by", commit=False)
    a = append_evidence_command(
        conn,
        incident_id=created.incident_id,
        kind="METRIC",
        fingerprint=f"fp-m-{uuid.uuid4().hex[:8]}",
        summary="err",
        producer="prometheus_collector",
        payload={"error_rate": 0.5},
        commit=False,
    )
    b = append_evidence_command(
        conn,
        incident_id=created.incident_id,
        kind="CHANGE",
        fingerprint=f"fp-c-{uuid.uuid4().hex[:8]}",
        summary="deploy",
        producer="change_collector",
        payload={"revision": "bad"},
        commit=False,
    )
    with pytest.raises(CausedByActorDenied, match="SYSTEM confirmation"):
        link_evidence_relation_command(
            conn,
            from_evidence_id=a.evidence_id,
            to_evidence_id=b.evidence_id,
            relation_type="CAUSED_BY",
            commit=False,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_system_confirm_deploy_class_writes_caused_by(conn: object) -> None:
    created = create_incident_command(conn, title="h10 confirm", commit=False)
    incident_id = created.incident_id
    metric = append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="METRIC",
        fingerprint=f"fp-m-{uuid.uuid4().hex[:8]}",
        summary="checkout errors",
        producer="prometheus_collector",
        payload={"error_rate": 0.6},
        commit=False,
    )
    change = append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="CHANGE",
        fingerprint=f"fp-c-{uuid.uuid4().hex[:8]}",
        summary="bad deploy",
        producer="change_collector",
        payload={"revision": "abc"},
        commit=False,
    )
    append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="ACTION_RESULT",
        fingerprint=f"fp-a-{uuid.uuid4().hex[:8]}",
        summary="rollback ok",
        producer="test_producer",
        payload={"action": "ROLLBACK_DEPLOYMENT"},
        commit=False,
    )
    proposed = propose_hypothesis_command(
        conn,
        incident_id=incident_id,
        statement="bad deployment caused checkout errors",
        cited_evidence_ids=[metric.evidence_key, change.evidence_key],
        hypothesis_class="bad_deployment",
        commit=False,
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE domain.hypothesis
            SET status = 'LEADING', leading_at = now(), updated_at = now()
            WHERE id = %s
            """,
            (str(proposed.hypothesis_id),),
        )
        cur.execute(
            """
            INSERT INTO domain.validation_result (
                incident_id, outcome, criteria, observations
            ) VALUES (%s, 'RECOVERED', '{}'::jsonb, '{}'::jsonb)
            """,
            (str(incident_id),),
        )

    with pytest.raises(ConfirmActorDenied):
        confirm_hypothesis_command(
            conn,
            incident_id=incident_id,
            hypothesis_id=proposed.hypothesis_id,
            actor=AI_SANDBOX_IDENTITY,
            commit=False,
        )

    # RECOVERED without deploy signals already covered in unit tests; here full path.
    result = confirm_hypothesis_command(
        conn,
        incident_id=incident_id,
        hypothesis_id=proposed.hypothesis_id,
        actor="system",
        commit=False,
    )
    assert result.status == "CONFIRMED"
    assert result.caused_by_written is True

    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM domain.hypothesis WHERE id = %s",
            (str(proposed.hypothesis_id),),
        )
        assert cur.fetchone()[0] == "CONFIRMED"
        cur.execute(
            """
            SELECT 1 FROM domain.evidence_relation
            WHERE relation_type = 'CAUSED_BY'
              AND from_evidence_id = %s AND to_evidence_id = %s
            """,
            (str(metric.evidence_id), str(change.evidence_id)),
        )
        assert cur.fetchone() is not None


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_recovered_alone_rejected_by_command(conn: object) -> None:
    created = create_incident_command(conn, title="h10 recovered only", commit=False)
    incident_id = created.incident_id
    metric = append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="METRIC",
        fingerprint=f"fp-m-{uuid.uuid4().hex[:8]}",
        summary="err",
        producer="prometheus_collector",
        payload={"error_rate": 0.4},
        commit=False,
    )
    proposed = propose_hypothesis_command(
        conn,
        incident_id=incident_id,
        statement="maybe deploy",
        cited_evidence_ids=[metric.evidence_key],
        hypothesis_class="bad_deployment",
        commit=False,
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE domain.hypothesis
            SET status = 'LEADING', leading_at = now()
            WHERE id = %s
            """,
            (str(proposed.hypothesis_id),),
        )
        cur.execute(
            """
            INSERT INTO domain.validation_result (incident_id, outcome)
            VALUES (%s, 'RECOVERED')
            """,
            (str(incident_id),),
        )
    with pytest.raises(ConfirmationRulesNotMet, match="CHANGE|insufficient|ACTION_RESULT"):
        confirm_hypothesis_command(
            conn,
            incident_id=incident_id,
            hypothesis_id=proposed.hypothesis_id,
            actor="system",
            commit=False,
        )
