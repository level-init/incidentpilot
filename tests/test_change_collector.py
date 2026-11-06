"""G9: bad deploy → Change + DEPLOYMENT Evidence in collect window."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest

from incidentpilot_adapters.changes import SimChangeSource
from incidentpilot_adapters.changes.catalog import scenario_changes_at
from incidentpilot_shared.collect_job import ALLOWED_COLLECTORS, DEFAULT_COLLECTORS

psycopg = pytest.importorskip("psycopg")


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.change LIMIT 1")
                cur.execute("SELECT 1 FROM domain.evidence LIMIT 1")
            return True
    except Exception:
        return False


def test_allowed_collectors_include_changes() -> None:
    assert "changes" in ALLOWED_COLLECTORS
    assert "changes" in DEFAULT_COLLECTORS


def test_job_from_payload_defaults_include_changes() -> None:
    """Dict payloads without collectors must use DEFAULT_COLLECTORS (incl. changes)."""
    from incidentpilot_worker.activities.collect_cycle import _job_from_payload

    job = _job_from_payload({"incident_id": "inc-1", "environment": "local"})
    assert job.collectors == DEFAULT_COLLECTORS
    assert "changes" in job.collectors


def test_sim_catalog_has_payment_deployment() -> None:
    stamp = datetime(2024, 8, 1, 12, 0, tzinfo=UTC)
    changes = scenario_changes_at(stamp)
    deploys = [c for c in changes if c.change_type == "DEPLOYMENT" and c.service_key == "payment"]
    assert len(deploys) == 1
    assert deploys[0].source_ref.startswith("sim:deploy:payment:")
    types = {c.change_type for c in changes}
    assert {"DEPLOYMENT", "COMMIT", "PULL_REQUEST", "FEATURE_FLAG", "CONFIG", "SCALE"} <= types


def test_sim_change_source_stamps_in_window() -> None:
    start = datetime(2024, 8, 1, 11, 0, tzinfo=UTC)
    end = datetime(2024, 8, 1, 12, 0, tzinfo=UTC)
    hits = SimChangeSource().list_changes(since=start, until=end, service="payment")
    assert any(c.change_type == "DEPLOYMENT" for c in hits)
    assert all(start <= c.observed_at <= end for c in hits)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_bad_deploy_appears_as_change_and_deployment_evidence() -> None:
    from incidentpilot_worker.collectors import collect_changes_for_incident

    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'G9 bad deploy', 1)
            """,
            (str(iid), f"INC-G9-{iid.hex[:8]}"),
        )
        conn.commit()

    start, end = 1_700_500_000.0, 1_700_500_900.0
    results = collect_changes_for_incident(
        incident_id=iid,
        start=start,
        end=end,
        source=SimChangeSource(),
    )
    assert results
    assert all(r.kind == "CHANGE" and r.producer == "change_collector" for r in results)
    assert any(r.inserted for r in results)

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.change_type, s.key, c.external_ref
            FROM domain.change c
            JOIN domain.service s ON s.id = c.service_id
            WHERE c.source = 'sim' AND s.key = 'payment' AND c.change_type = 'DEPLOYMENT'
            ORDER BY c.observed_at DESC
            LIMIT 1
            """,
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "DEPLOYMENT"
        assert row[1] == "payment"
        assert row[2].startswith("sim:deploy:payment:")

        cur.execute(
            """
            SELECT kind, producer, payload->>'change_type', payload->>'service_key',
                   observed_at
            FROM domain.evidence
            WHERE incident_id = %s AND kind = 'CHANGE'
              AND payload->>'change_type' = 'DEPLOYMENT'
              AND payload->>'service_key' = 'payment'
            """,
            (str(iid),),
        )
        ev = cur.fetchone()
        assert ev is not None
        assert ev[0] == "CHANGE"
        assert ev[1] == "change_collector"
        assert ev[2] == "DEPLOYMENT"
        assert ev[3] == "payment"
        observed = ev[4]
        assert (
            datetime.fromtimestamp(start, tz=UTC)
            <= observed.replace(tzinfo=UTC)
            <= (datetime.fromtimestamp(end, tz=UTC))
        )

    # Dedup on second collect
    again = collect_changes_for_incident(
        incident_id=iid, start=start, end=end, source=SimChangeSource()
    )
    assert again
    assert all(r.inserted is False for r in again)
