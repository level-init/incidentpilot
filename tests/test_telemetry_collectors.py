"""G3: Prometheus / Loki / Tempo collectors → Evidence kinds."""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "shared", ROOT / "worker", ROOT / "adapters", ROOT / "api"):
    sys.path.insert(0, str(p))

from incidentpilot_adapters.telemetry.loki import LokiQueryResult  # noqa: E402
from incidentpilot_adapters.telemetry.prometheus import PrometheusQueryResult  # noqa: E402
from incidentpilot_adapters.telemetry.tempo import TempoQueryResult  # noqa: E402
from incidentpilot_shared.temporal_queues import TaskQueue, contract_for  # noqa: E402
from incidentpilot_worker.collectors import (  # noqa: E402
    collect_logs_for_incident,
    collect_metrics_for_incident,
    collect_traces_for_incident,
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
                cur.execute("SELECT 1 FROM domain.evidence LIMIT 1")
            return True
    except Exception:
        return False


@dataclass
class _FakeProm:
    def query_range(
        self,
        query: str,
        *,
        start: float,
        end: float,
        step: str = "30s",
        max_series: int = 20,
    ) -> PrometheusQueryResult:
        return PrometheusQueryResult(
            query=query,
            start=start,
            end=end,
            step=step,
            result_type="matrix",
            series=[{"metric": {"__name__": "up"}, "values": [[start, "1"]]}],
        )


@dataclass
class _FakeLoki:
    def query_range(
        self,
        query: str,
        *,
        start: float,
        end: float,
        limit: int = 100,
        max_streams: int = 10,
    ) -> LokiQueryResult:
        return LokiQueryResult(
            query=query,
            start_ns=int(start * 1e9),
            end_ns=int(end * 1e9),
            streams=[{"stream": {"job": "sim"}, "values": [["1", "error payment"]]}],
        )


@dataclass
class _FakeTempo:
    def search(
        self,
        query: str,
        *,
        start: float,
        end: float,
        limit: int = 20,
    ) -> TempoQueryResult:
        return TempoQueryResult(
            query=query,
            start=start,
            end=end,
            traces=[
                {
                    "traceID": "abc",
                    "rootServiceName": "checkout",
                    "durationMs": 12,
                }
            ],
        )


def _incident() -> uuid.UUID:
    iid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'G3 collect', 1)
            """,
            (str(iid), f"INC-G3-{iid.hex[:8]}"),
        )
        conn.commit()
    return iid


def test_evidence_worker_registers_collector_activities() -> None:
    """Collector activities are on evidence queue, not implied on general."""
    assert contract_for(TaskQueue.EVIDENCE).privilege_class == "collector"
    # build_worker needs a Client — use a lightweight stub via activity names inspect
    from incidentpilot_worker.activities import collectors as mod

    assert hasattr(mod, "collect_prometheus_metrics")
    assert hasattr(mod, "collect_loki_logs")
    assert hasattr(mod, "collect_tempo_traces")


def test_general_worker_factory_excludes_collector_env_contract() -> None:
    """Documented privilege split: evidence-worker is collector class."""
    assert contract_for(TaskQueue.GENERAL).privilege_class != "collector"
    assert contract_for(TaskQueue.EVIDENCE).consumer_process == "evidence-worker"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_collect_window_writes_metric_log_trace_kinds() -> None:
    iid = _incident()
    start, end = 1_700_000_000.0, 1_700_000_900.0
    metric = collect_metrics_for_incident(
        incident_id=iid,
        start=start,
        end=end,
        query="up",
        client=_FakeProm(),  # type: ignore[arg-type]
        blob_store=None,
    )
    log = collect_logs_for_incident(
        incident_id=iid,
        start=start,
        end=end,
        query='{job="sim"}',
        client=_FakeLoki(),  # type: ignore[arg-type]
        blob_store=None,
    )
    trace = collect_traces_for_incident(
        incident_id=iid,
        start=start,
        end=end,
        query="{}",
        client=_FakeTempo(),  # type: ignore[arg-type]
        blob_store=None,
    )
    assert metric.kind == "METRIC" and metric.producer == "prometheus_collector"
    assert log.kind == "LOG" and log.producer == "loki_collector"
    assert trace.kind == "TRACE" and trace.producer == "tempo_collector"
    assert metric.inserted and log.inserted and trace.inserted

    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT kind FROM domain.evidence WHERE incident_id = %s ORDER BY kind",
            (str(iid),),
        )
        kinds = [r[0] for r in cur.fetchall()]
    assert kinds == ["LOG", "METRIC", "TRACE"]


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_collect_dedup_same_window() -> None:
    iid = _incident()
    start, end = 1_700_100_000.0, 1_700_100_600.0
    first = collect_metrics_for_incident(
        incident_id=iid,
        start=start,
        end=end,
        query="up",
        client=_FakeProm(),  # type: ignore[arg-type]
        blob_store=None,
    )
    second = collect_metrics_for_incident(
        incident_id=iid,
        start=start,
        end=end,
        query="up",
        client=_FakeProm(),  # type: ignore[arg-type]
        blob_store=None,
    )
    assert first.evidence_id == second.evidence_id
    assert first.inserted is True
    assert second.inserted is False
