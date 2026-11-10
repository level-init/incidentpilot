"""J8: validation outcome routing — RESOLVED / PLANNING_REMEDIATION / DEGRADED."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import (
    ROUTE_DEGRADED,
    ROUTE_PLANNING_REMEDIATION,
    ROUTE_RESOLVED,
    record_validation_result_command,
    route_validation_outcome_command,
)
from incidentpilot_shared.domain.transitions import (
    IllegalTransitionError,
    IncidentState,
    transition_incident,
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


def _seed(conn: object, *, state: str = "VALIDATING") -> tuple[uuid.UUID, uuid.UUID]:
    incident_id = uuid.uuid4()
    action_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, %s, 'j8 route', 4)
            """,
            (str(incident_id), f"INC-J8-{uuid.uuid4().hex[:8]}", state),
        )
        cur.execute(
            """
            INSERT INTO domain.action (
                id, incident_id, action_type, current_version, status, proposed_by
            ) VALUES (%s, %s, 'ROLLBACK_DEPLOYMENT', 1, 'SUCCEEDED', 'system')
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
    return incident_id, attempt_id


def test_no_validating_to_mitigating_shortcut() -> None:
    with pytest.raises(IllegalTransitionError, match="VALIDATING → MITIGATING"):
        transition_incident(
            incident_id=uuid.uuid4(),
            current_state=IncidentState.VALIDATING,
            expected_revision=1,
            actual_revision=1,
            to_state=IncidentState.MITIGATING,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_recovered_routes_to_resolved(conn: object) -> None:
    incident_id, attempt_id = _seed(conn)
    record_validation_result_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt_id,
        outcome="RECOVERED",
        transition=True,
        commit=False,
    )
    routed = route_validation_outcome_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt_id,
        commit=False,
    )
    assert routed.route == ROUTE_RESOLVED
    assert routed.to_state == "RESOLVED"
    assert "RECOVERED→RESOLVED" in routed.steps


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_no_improvement_routes_to_planning_remediation(conn: object) -> None:
    """PARTIAL/NO_IMPROVEMENT ← STILL_DEGRADED → DIAGNOSED (planning)."""
    incident_id, attempt_id = _seed(conn)
    record_validation_result_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt_id,
        outcome="STILL_DEGRADED",
        transition=True,
        commit=False,
    )
    routed = route_validation_outcome_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt_id,
        commit=False,
    )
    assert routed.route == ROUTE_PLANNING_REMEDIATION
    assert routed.to_state == "DIAGNOSED"
    assert "DEGRADED→DIAGNOSED" in routed.steps


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_unknown_also_replans(conn: object) -> None:
    incident_id, attempt_id = _seed(conn)
    record_validation_result_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt_id,
        outcome="UNKNOWN",
        transition=True,
        commit=False,
    )
    routed = route_validation_outcome_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt_id,
        commit=False,
    )
    assert routed.route == ROUTE_PLANNING_REMEDIATION
    assert routed.to_state == "DIAGNOSED"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_regression_routes_to_degraded(conn: object) -> None:
    """REGRESSION ← FAILED_VALIDATION → stay DEGRADED."""
    incident_id, attempt_id = _seed(conn)
    record_validation_result_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt_id,
        outcome="FAILED_VALIDATION",
        transition=True,
        commit=False,
    )
    routed = route_validation_outcome_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt_id,
        commit=False,
    )
    assert routed.route == ROUTE_DEGRADED
    assert routed.to_state == "DEGRADED"
    assert not any(s.endswith("→DIAGNOSED") for s in routed.steps)
