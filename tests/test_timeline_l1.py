"""L1: TimelineEvent process chronicle — bad-deploy readable chronology."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import (
    append_action_result_evidence_command,
    create_approval_command,
    create_incident_command,
    create_runbook_command,
    create_runbook_version_command,
    decide_approval_command,
    evaluate_policy_command,
    pin_runbook_version_command,
    propose_action_command,
    publish_runbook_version_command,
    record_validation_result_command,
    reserve_execution_attempt_command,
    route_validation_outcome_command,
    transition_incident_command,
)
from incidentpilot_shared.domain.transitions import IncidentState
from incidentpilot_shared.timeline import (
    BAD_DEPLOY_CHRONOLOGY,
    TIMELINE_EVENT_TYPES,
    list_timeline_event_types,
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
                cur.execute("SELECT 1 FROM domain.timeline_event LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def _is_subsequence(expected: tuple[str, ...], actual: list[str]) -> bool:
    it = iter(actual)
    return all(e in it for e in expected)


def test_catalog_covers_bad_deploy_milestones() -> None:
    assert set(BAD_DEPLOY_CHRONOLOGY).issubset(TIMELINE_EVENT_TYPES)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_bad_deploy_path_readable_chronology(conn: object) -> None:
    """Level-2 rollback path emits a readable process chronicle (L1 AC)."""
    created = create_incident_command(
        conn,
        title="l1 bad deploy chronology",
        severity="SEV2",
        commit=False,
    )
    incident_id = created.incident_id

    t = transition_incident_command(
        conn,
        incident_id=incident_id,
        expected_revision=1,
        to_state=IncidentState.INVESTIGATING,
        commit=False,
    )
    t = transition_incident_command(
        conn,
        incident_id=incident_id,
        expected_revision=t.new_revision,
        to_state=IncidentState.DIAGNOSED,
        via_diagnose_gate=True,
        commit=False,
    )
    t = transition_incident_command(
        conn,
        incident_id=incident_id,
        expected_revision=t.new_revision,
        to_state=IncidentState.AWAITING_APPROVAL,
        commit=False,
    )

    rb = create_runbook_command(
        conn,
        key=f"l1.rb.{uuid.uuid4().hex[:8]}",
        title="L1 RB",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# l1 rollback",
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

    params = {"revision": "prev", "deployment": "checkout"}
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
        decided_by="harness:l1",
        commit=False,
    )

    t = transition_incident_command(
        conn,
        incident_id=incident_id,
        expected_revision=t.new_revision,
        to_state=IncidentState.MITIGATING,
        commit=False,
    )
    attempt = reserve_execution_attempt_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        commit=False,
    )
    append_action_result_evidence_command(
        conn,
        incident_id=incident_id,
        attempt_id=attempt.attempt_id,
        action_id=proposed.action_id,
        action_version=proposed.version,
        action_type="ROLLBACK_DEPLOYMENT",
        ok=True,
        summary="rollback applied (sim)",
        adapter_result={"revision": "prev"},
        commit=False,
    )

    t = transition_incident_command(
        conn,
        incident_id=incident_id,
        expected_revision=t.new_revision,
        to_state=IncidentState.VALIDATING,
        commit=False,
    )
    record_validation_result_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt.attempt_id,
        outcome="RECOVERED",
        action_id=proposed.action_id,
        action_version=proposed.version,
        transition=True,
        commit=False,
    )
    route_validation_outcome_command(
        conn,
        incident_id=incident_id,
        execution_attempt_id=attempt.attempt_id,
        commit=False,
    )

    types = list_timeline_event_types(conn, incident_id=incident_id)
    assert types[0] == "INCIDENT_CREATED"
    assert _is_subsequence(BAD_DEPLOY_CHRONOLOGY, types), (
        f"expected subsequence {BAD_DEPLOY_CHRONOLOGY} not found in {types}"
    )
    unknown = set(types) - TIMELINE_EVENT_TYPES
    assert not unknown, f"unexpected event types: {unknown}"
