"""Bounded telemetry collect → Evidence via registered producers (G3).

Runs only in evidence-worker privilege class. Source URLs come from
PROMETHEUS_URL / LOKI_URL / TEMPO_URL — never from the general worker.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from incidentpilot_adapters.telemetry import LokiClient, PrometheusClient, TempoClient
from incidentpilot_worker.commands import append_evidence_command
from incidentpilot_worker.db import connect

# Hard caps for G3 demo collects
_MAX_WINDOW_SECONDS = 3600
_DEFAULT_PROM_QUERY = 'up'
_DEFAULT_LOKI_QUERY = '{job=~".+"}'
_DEFAULT_TEMPO_QUERY = '{}'


@dataclass(frozen=True, slots=True)
class CollectResult:
    kind: str
    producer: str
    evidence_id: UUID | None
    fingerprint: str
    inserted: bool
    summary: str


def _fingerprint(producer: str, kind: str, query: str, start: float, end: float) -> str:
    bucket = int(start // 60)
    material = f"{producer}|{kind}|{query}|{bucket}|{int(end - start)}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{producer}:{kind.lower()}:{digest}"


def _clamp_window(start: float, end: float) -> tuple[float, float]:
    if end < start:
        start, end = end, start
    if end - start > _MAX_WINDOW_SECONDS:
        start = end - _MAX_WINDOW_SECONDS
    return start, end


def collect_metrics_for_incident(
    *,
    incident_id: UUID,
    start: float,
    end: float,
    query: str = _DEFAULT_PROM_QUERY,
    client: PrometheusClient | None = None,
) -> CollectResult:
    start, end = _clamp_window(start, end)
    prom = client or PrometheusClient()
    result = prom.query_range(query, start=start, end=end)
    producer = "prometheus_collector"
    fp = _fingerprint(producer, "METRIC", query, start, end)
    summary = f"prometheus query_range series={len(result.series)} q={query[:80]}"
    payload: dict[str, Any] = {
        "query": result.query,
        "start": result.start,
        "end": result.end,
        "step": result.step,
        "result_type": result.result_type,
        "series": result.series,
    }
    with connect() as conn:
        out = append_evidence_command(
            conn,
            incident_id=incident_id,
            kind="METRIC",
            fingerprint=fp,
            summary=summary,
            producer=producer,
            payload=payload,
            provenance={"source": "prometheus", "window": {"start": start, "end": end}},
            observed_at=datetime.fromtimestamp(end, tz=UTC),
            commit=True,
        )
    return CollectResult(
        kind="METRIC",
        producer=producer,
        evidence_id=out.evidence_id,
        fingerprint=fp,
        inserted=out.inserted,
        summary=summary,
    )


def collect_logs_for_incident(
    *,
    incident_id: UUID,
    start: float,
    end: float,
    query: str = _DEFAULT_LOKI_QUERY,
    client: LokiClient | None = None,
) -> CollectResult:
    start, end = _clamp_window(start, end)
    loki = client or LokiClient()
    result = loki.query_range(query, start=start, end=end)
    producer = "loki_collector"
    fp = _fingerprint(producer, "LOG", query, start, end)
    line_count = sum(len(s.get("values") or []) for s in result.streams)
    summary = f"loki query_range streams={len(result.streams)} lines={line_count}"
    payload = {
        "query": result.query,
        "start_ns": result.start_ns,
        "end_ns": result.end_ns,
        "streams": result.streams,
    }
    with connect() as conn:
        out = append_evidence_command(
            conn,
            incident_id=incident_id,
            kind="LOG",
            fingerprint=fp,
            summary=summary,
            producer=producer,
            payload=payload,
            provenance={"source": "loki", "window": {"start": start, "end": end}},
            observed_at=datetime.fromtimestamp(end, tz=UTC),
            commit=True,
        )
    return CollectResult(
        kind="LOG",
        producer=producer,
        evidence_id=out.evidence_id,
        fingerprint=fp,
        inserted=out.inserted,
        summary=summary,
    )


def collect_traces_for_incident(
    *,
    incident_id: UUID,
    start: float,
    end: float,
    query: str = _DEFAULT_TEMPO_QUERY,
    client: TempoClient | None = None,
) -> CollectResult:
    start, end = _clamp_window(start, end)
    tempo = client or TempoClient()
    result = tempo.search(query, start=start, end=end)
    producer = "tempo_collector"
    fp = _fingerprint(producer, "TRACE", query, start, end)
    summary = f"tempo search traces={len(result.traces)} q={query[:80]}"
    payload = {
        "query": result.query,
        "start": result.start,
        "end": result.end,
        "traces": result.traces,
    }
    with connect() as conn:
        out = append_evidence_command(
            conn,
            incident_id=incident_id,
            kind="TRACE",
            fingerprint=fp,
            summary=summary,
            producer=producer,
            payload=payload,
            provenance={"source": "tempo", "window": {"start": start, "end": end}},
            observed_at=datetime.fromtimestamp(end, tz=UTC),
            commit=True,
        )
    return CollectResult(
        kind="TRACE",
        producer=producer,
        evidence_id=out.evidence_id,
        fingerprint=fp,
        inserted=out.inserted,
        summary=summary,
    )


def collect_incident_window(
    *,
    incident_id: UUID,
    start: float | None = None,
    end: float | None = None,
    metrics_query: str = _DEFAULT_PROM_QUERY,
    logs_query: str = _DEFAULT_LOKI_QUERY,
    traces_query: str = _DEFAULT_TEMPO_QUERY,
) -> list[CollectResult]:
    """Collect METRIC + LOG + TRACE for an incident time window."""
    now = datetime.now(tz=UTC).timestamp()
    end_ts = end if end is not None else now
    start_ts = start if start is not None else end_ts - 900
    start_ts, end_ts = _clamp_window(start_ts, end_ts)
    return [
        collect_metrics_for_incident(
            incident_id=incident_id, start=start_ts, end=end_ts, query=metrics_query
        ),
        collect_logs_for_incident(
            incident_id=incident_id, start=start_ts, end=end_ts, query=logs_query
        ),
        collect_traces_for_incident(
            incident_id=incident_id, start=start_ts, end=end_ts, query=traces_query
        ),
    ]


def collect_result_to_dict(result: CollectResult) -> dict[str, Any]:
    return {
        "kind": result.kind,
        "producer": result.producer,
        "evidence_id": str(result.evidence_id) if result.evidence_id else None,
        "fingerprint": result.fingerprint,
        "inserted": result.inserted,
        "summary": result.summary,
    }


def collect_window_payload(results: list[CollectResult]) -> str:
    return json.dumps([collect_result_to_dict(r) for r in results])
