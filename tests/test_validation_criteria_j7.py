"""J7: checkout_recovery criteria + one ValidationResult per attempt."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import record_validation_result_command
from incidentpilot_shared.processors.validation import (
    ERROR_RATE_MAX,
    OUTCOME_RECOVERED,
    OUTCOME_STILL_DEGRADED,
    OUTCOME_UNKNOWN,
    RULE_CHECKOUT_RECOVERY,
    evaluate_checkout_recovery,
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
                cur.execute("SELECT 1 FROM domain.validation_result LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def test_documented_thresholds() -> None:
    assert ERROR_RATE_MAX == 0.05
    assert RULE_CHECKOUT_RECOVERY == "checkout_recovery.v1"


def test_recovered_when_error_rate_below_threshold() -> None:
    verdict = evaluate_checkout_recovery(
        metric_rows=[
            {
                "id": str(uuid.uuid4()),
                "payload": {"value": 0.01, "query": "checkout_error_rate"},
            }
        ],
        action_result_present=True,
    )
    assert verdict.outcome == OUTCOME_RECOVERED
    assert verdict.criteria["error_rate_max"] == 0.05


def test_still_degraded_when_error_rate_high() -> None:
    verdict = evaluate_checkout_recovery(
        metric_rows=[{"id": str(uuid.uuid4()), "payload": {"error_rate": 0.12}}],
        action_result_present=True,
    )
    assert verdict.outcome == OUTCOME_STILL_DEGRADED


def test_unknown_without_metrics_or_action_result() -> None:
    assert (
        evaluate_checkout_recovery(
            metric_rows=[], action_result_present=True
        ).outcome
        == OUTCOME_UNKNOWN
    )
    assert (
        evaluate_checkout_recovery(
            metric_rows=[{"id": "x", "payload": {"value": 0.01}}],
            action_result_present=False,
        ).outcome
        == OUTCOME_UNKNOWN
    )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_one_validation_result_per_attempt(conn: object) -> None:
    incident_id = uuid.uuid4()
    action_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'VALIDATING', 'j7 uniq', 4)
            """,
            (str(incident_id), f"INC-J7-{uuid.uuid4().hex[:8]}"),
        )
        cur.execute(
            """
            INSERT INTO domain.action (
                id, incident_id, action_type, current_version, status, proposed_by
            ) VALUES (%s, %s, 'ROLLBACK_DEPLOYMENT', 1, 'EXECUTING', 'system')
            """,
            (str(action_id), str(incident_id)),
        )
        cur.execute(
            """
            INSERT INTO domain.action_version (
                action_id, version, action_type, proposed_by
            ) VALUES (%s, 1, 'ROLLBACK_DEPLOYMENT', 'system')
            """,
            (str(action_id),),
        )
        cur.execute(
            """
            INSERT INTO domain.execution_attempt (
                id, action_id, action_version, attempt_number, state
            ) VALUES (%s, %s, 1, 1, 'SUCCEEDED')
            """,
            (str(attempt_id), str(action_id)),
        )

    first = record_validation_result_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt_id,
        outcome="RECOVERED",
        criteria={"rule": RULE_CHECKOUT_RECOVERY},
        observations={"error_rates": [0.01]},
        action_id=action_id,
        action_version=1,
        commit=False,
    )
    assert first.inserted is True
    assert first.incident_state == "RECOVERED"

    second = record_validation_result_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt_id,
        outcome="STILL_DEGRADED",
        commit=False,
    )
    assert second.inserted is False
    assert second.validation_result_id == first.validation_result_id
    assert second.outcome == "RECOVERED"

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM domain.validation_result
            WHERE execution_attempt_id = %s
            """,
            (str(attempt_id),),
        )
        assert cur.fetchone()[0] == 1
