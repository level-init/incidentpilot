"""H7: ImpactSnapshot + SLOBurn calculators, commands, and query path."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import (
    MissingEvidenceCitationError,
    append_evidence_command,
    compute_impact_snapshot_command,
    compute_slo_burn_command,
    record_impact_snapshot_command,
)
from incidentpilot_shared.processors.impact import (
    impact_from_metrics,
    slo_burn_from_metrics,
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
                cur.execute("SELECT 1 FROM domain.impact_snapshot LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def test_impact_calculator_ranges() -> None:
    low = impact_from_metrics([{"error_rate": 0.05}])
    assert low is not None
    assert low.severity == "SEV3"
    lo, hi = low.metrics["affected_users_range"]
    assert lo <= low.estimated_affected_users <= hi
    assert low.metrics["revenue_impact_usd_heuristic"]["accounting"] == "heuristic_not_ledger"

    mid = impact_from_metrics([{"error_rate": 0.25}])
    assert mid is not None
    assert mid.severity == "SEV2"

    high = impact_from_metrics(
        [{"series": [{"values": [[1, "0.1"], [2, "0.6"]]}]}]
    )
    assert high is not None
    assert high.severity == "SEV1"


def test_slo_burn_calculator_ranges() -> None:
    est = slo_burn_from_metrics({"error_rate": 0.01}, slo_target=0.999)
    assert est is not None
    assert est.burn_rate == pytest.approx(10.0)
    assert 0.0 <= est.error_budget_remaining <= 1.0
    assert est.payload["formula"].startswith("burn_rate")


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_missing_citation_rejected(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'h7', 1)
            """,
            (str(incident_id), f"INC-H7-{uuid.uuid4().hex[:8]}"),
        )
    with pytest.raises(MissingEvidenceCitationError):
        record_impact_snapshot_command(
            conn,
            incident_id=incident_id,
            cited_evidence_ids=["EV-missing"],
            severity="SEV2",
            commit=False,
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_compute_snapshot_during_incident_window(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'h7 impact', 1)
            RETURNING opened_at
            """,
            (str(incident_id), f"INC-H7-{uuid.uuid4().hex[:8]}"),
        )
        opened_at = cur.fetchone()[0]

    append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="METRIC",
        fingerprint=f"fp-{uuid.uuid4().hex}",
        summary="checkout error rate",
        payload={"error_rate": 0.22, "series": [{"values": [[1, "0.1"], [2, "0.22"]]}]},
        producer="test_producer",
        commit=False,
    )

    snap = compute_impact_snapshot_command(conn, incident_id=incident_id, commit=False)
    burn = compute_slo_burn_command(conn, incident_id=incident_id, commit=False)
    assert snap.severity in {"SEV1", "SEV2", "SEV3"}
    assert snap.estimated_affected_users is not None
    assert burn.burn_rate is not None

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT captured_at, severity, estimated_affected_users,
                   provenance->>'quality_rule_id',
                   metrics->'affected_users_range'
            FROM domain.impact_snapshot
            WHERE id = %s
            """,
            (str(snap.snapshot_id),),
        )
        captured_at, severity, users, rule, users_range = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM domain.impact_snapshot WHERE incident_id = %s",
            (str(incident_id),),
        )
        count = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM domain.slo_burn WHERE incident_id = %s",
            (str(incident_id),),
        )
        burn_count = cur.fetchone()[0]

    assert count >= 1
    assert burn_count >= 1
    assert captured_at >= opened_at
    assert severity == snap.severity
    assert rule == "impact_from_metrics.v1"
    assert users_range[0] <= users <= users_range[1]
