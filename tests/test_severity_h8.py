"""H8: SYSTEM severity updater — rules engine; AI cannot set severity."""

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
    SeverityActorDenied,
    attach_alert_command,
    create_incident_command,
    record_impact_snapshot_command,
    record_slo_burn_command,
    update_incident_severity_command,
    upsert_alert_command,
)
from incidentpilot_shared.processors.severity import (
    RULE_SEVERITY_FROM_SIGNALS,
    severity_from_signals,
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
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'domain'
                      AND table_name = 'service'
                      AND column_name = 'criticality'
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


def test_rules_worst_of_hint_impact_slo() -> None:
    d = severity_from_signals(
        severity_hint="warning",
        impact_severity="SEV2",
        burn_rate=20.0,
        criticality="MEDIUM",
    )
    assert d.severity == "SEV1"
    assert d.quality_rule_id == RULE_SEVERITY_FROM_SIGNALS
    assert d.inputs["worst_source"] == "slo"


def test_rules_criticality_escalates() -> None:
    base = severity_from_signals(
        severity_hint="SEV3",
        impact_severity="SEV3",
        criticality="MEDIUM",
    )
    escalated = severity_from_signals(
        severity_hint="SEV3",
        impact_severity="SEV3",
        criticality="CRITICAL",
    )
    assert base.severity == "SEV3"
    assert escalated.severity == "SEV2"


def test_ai_tools_cannot_set_severity() -> None:
    registry = default_ai_tool_registry()
    for name in (
        "set_severity",
        "update_severity",
        "severity_update",
        "incident_set_severity",
        "update_incident_severity",
    ):
        assert name in DENIED_TOOL_NAMES
        assert registry.is_allowed(name) is False
        with pytest.raises(ToolDeniedError, match=AI_SANDBOX_IDENTITY):
            registry.require_allowed(name)


@pytest.mark.skipif(not _db_available(), reason="Postgres/H8 migration not reachable")
def test_ai_actor_denied_on_severity_command(conn: object) -> None:
    created = create_incident_command(conn, title="h8 deny", severity="SEV3", commit=False)
    with pytest.raises(SeverityActorDenied, match="SYSTEM rules only"):
        update_incident_severity_command(
            conn,
            incident_id=created.incident_id,
            actor=AI_SANDBOX_IDENTITY,
            commit=False,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres/H8 migration not reachable")
def test_system_updater_from_impact_and_slo(conn: object) -> None:
    created = create_incident_command(
        conn,
        title="h8 update",
        severity="SEV3",
        service_key="checkout",
        commit=False,
    )
    incident_id = created.incident_id
    # Synthetic impact + SLO without METRIC evidence (record_* allows SYSTEM insert).
    with conn.cursor() as cur:
        ev_id = uuid.uuid4()
        ev_key = f"EV-h8-{ev_id.hex[:8]}"
        cur.execute(
            """
            INSERT INTO domain.evidence (
                id, evidence_key, incident_id, kind, fingerprint, summary,
                payload, provenance, observed_at, producer
            ) VALUES (
                %s, %s, %s, 'METRIC', %s, 'h8 metric',
                '{}'::jsonb, '{}'::jsonb, now(), 'metrics_collector'
            )
            """,
            (str(ev_id), ev_key, str(incident_id), f"fp-h8-{uuid.uuid4().hex[:8]}"),
        )
    record_impact_snapshot_command(
        conn,
        incident_id=incident_id,
        cited_evidence_ids=[ev_key],
        severity="SEV2",
        customer_impact_summary="h8",
        estimated_affected_users=50,
        commit=False,
    )
    record_slo_burn_command(
        conn,
        incident_id=incident_id,
        cited_evidence_ids=[ev_key],
        slo_key="checkout_availability",
        window_label="1h",
        burn_rate=20.0,
        error_budget_remaining=0.05,
        commit=False,
    )
    alert = upsert_alert_command(
        conn,
        fingerprint=f"fp-alert-h8-{uuid.uuid4().hex[:8]}",
        source="test",
        status="firing",
        labels={"severity": "warning"},
        commit=False,
    )
    attach_alert_command(conn, alert_id=alert.alert_id, incident_id=incident_id, commit=False)

    result = update_incident_severity_command(
        conn, incident_id=incident_id, actor="system", commit=False
    )
    assert result.previous_severity == "SEV3"
    assert result.severity == "SEV1"
    assert result.changed is True
    assert "slo" in result.explanation or result.inputs.get("slo_severity") == "SEV1"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT severity FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        assert cur.fetchone()[0] == "SEV1"
        cur.execute(
            """
            SELECT event_type FROM domain.timeline_event
            WHERE incident_id = %s AND event_type = 'SEVERITY_UPDATE'
            """,
            (str(incident_id),),
        )
        assert cur.fetchone() is not None
