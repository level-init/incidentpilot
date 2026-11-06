"""G4: deterministic processors — DERIVED_FROM + quality_rule_id; not RAW."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))

from incidentpilot_shared.domain.commands import (  # noqa: E402
    append_evidence_command,
)
from incidentpilot_shared.processors.baseline import (  # noqa: E402
    RULE_BASELINE_COMPARE,
    baseline_compare,
)
from incidentpilot_shared.processors.runner import (  # noqa: E402
    process_log_top_errors,
    process_metric_baseline,
)
from incidentpilot_shared.processors.top_errors import (  # noqa: E402
    RULE_TOP_ERRORS,
    top_errors,
)

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
                cur.execute("SELECT 1 FROM domain.evidence_relation LIMIT 1")
            return True
    except Exception:
        return False


def test_baseline_compare_fixture() -> None:
    payload = {
        "query": "up",
        "series": [
            {
                "metric": {"__name__": "http_errors"},
                "values": [[1, "1"], [2, "1"], [3, "5"]],
            }
        ],
    }
    result = baseline_compare(payload, threshold_ratio=2.0)
    assert result is not None
    assert result.quality_rule_id == RULE_BASELINE_COMPARE
    assert result.payload["comparisons"][0]["breached"] is True
    assert result.payload["comparisons"][0]["latest"] == 5.0


def test_top_errors_fixture() -> None:
    payload = {
        "query": '{job="sim"}',
        "streams": [
            {
                "stream": {"job": "sim"},
                "values": [
                    ["1", "ERROR payment timeout id=12"],
                    ["2", "ERROR payment timeout id=99"],
                    ["3", "WARN cache miss"],
                    ["4", "ERROR payment timeout id=7"],
                ],
            }
        ],
    }
    result = top_errors(payload, limit=3)
    assert result is not None
    assert result.quality_rule_id == RULE_TOP_ERRORS
    assert result.payload["groups"][0]["count"] == 3
    assert "payment timeout" in result.payload["groups"][0]["pattern"]


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_derived_cites_raw_parent_not_raw_layer() -> None:
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'G4 derived', 1)
            """,
            (str(iid), f"INC-G4-{iid.hex[:8]}"),
        )
        parent = append_evidence_command(
            conn,
            incident_id=iid,
            kind="METRIC",
            fingerprint=f"prometheus_collector:g4-{uuid.uuid4().hex}",
            summary="raw metric",
            producer="prometheus_collector",
            payload={
                "query": "up",
                "series": [
                    {
                        "metric": {"__name__": "err"},
                        "values": [[1, "1"], [2, "1"], [3, "4"]],
                    }
                ],
            },
            provenance={"layer": "RAW", "source": "prometheus"},
            commit=False,
        )
        derived = process_metric_baseline(
            conn,
            incident_id=iid,
            parent_evidence_id=parent.evidence_id,
            metric_payload={
                "query": "up",
                "series": [
                    {
                        "metric": {"__name__": "err"},
                        "values": [[1, "1"], [2, "1"], [3, "4"]],
                    }
                ],
            },
            commit=False,
        )
        assert derived is not None
        conn.commit()

        cur.execute(
            "SELECT provenance, producer, kind FROM domain.evidence WHERE id = %s",
            (str(derived.evidence_id),),
        )
        prov, producer, kind = cur.fetchone()
        assert producer == "deterministic_processor"
        assert kind == "OTHER"
        assert prov["layer"] == "DETERMINISTIC_DERIVED"
        assert prov["layer"] != "RAW"
        assert prov["quality_rule_id"] == RULE_BASELINE_COMPARE
        assert str(parent.evidence_id) in prov["parent_evidence_ids"]

        cur.execute(
            """
            SELECT relation_type FROM domain.evidence_relation
            WHERE from_evidence_id = %s AND to_evidence_id = %s
            """,
            (str(derived.evidence_id), str(parent.evidence_id)),
        )
        assert cur.fetchone()[0] == "DERIVED_FROM"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_top_errors_derived_relation() -> None:
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'G4 top errors', 1)
            """,
            (str(iid), f"INC-G4E-{iid.hex[:8]}"),
        )
        log_payload = {
            "query": '{job="x"}',
            "streams": [
                {
                    "stream": {},
                    "values": [["1", "boom 1"], ["2", "boom 2"], ["3", "other"]],
                }
            ],
        }
        parent = append_evidence_command(
            conn,
            incident_id=iid,
            kind="LOG",
            fingerprint=f"loki_collector:g4-{uuid.uuid4().hex}",
            summary="raw logs",
            producer="loki_collector",
            payload=log_payload,
            commit=False,
        )
        derived = process_log_top_errors(
            conn,
            incident_id=iid,
            parent_evidence_id=parent.evidence_id,
            log_payload=log_payload,
            commit=True,
        )
        assert derived is not None
        cur.execute(
            """
            SELECT count(*) FROM domain.evidence_relation
            WHERE from_evidence_id = %s AND relation_type = 'DERIVED_FROM'
            """,
            (str(derived.evidence_id),),
        )
        assert cur.fetchone()[0] == 1
