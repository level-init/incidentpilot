"""Bounded telemetry + change collect → Evidence (G3/G5/G9).

Runs only in evidence-worker privilege class. Source URLs come from
PROMETHEUS_URL / LOKI_URL / TEMPO_URL — never from the general worker.

RAW rows upload to MinIO/S3 when configured; object-store failure falls back
to MEDIUM quality + content hash / external_ref (never fake HIGH).

Change collect (G9) upserts ``domain.change`` then emits ``kind=CHANGE`` Evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from incidentpilot_adapters.blob import BlobStore, resolve_evidence_blob_store
from incidentpilot_adapters.changes import ChangeSource, SimChangeSource
from incidentpilot_adapters.telemetry import LokiClient, PrometheusClient, TempoClient
from incidentpilot_shared.evidence_raw import append_raw_evidence_with_blob
from incidentpilot_worker.commands import append_evidence_command, upsert_change_command
from incidentpilot_worker.db import connect

# Hard caps for G3 demo collects
_MAX_WINDOW_SECONDS = 3600
_DEFAULT_PROM_QUERY = "up"
_DEFAULT_LOKI_QUERY = '{job=~".+"}'
_DEFAULT_TEMPO_QUERY = "{}"


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


def _blob_store(blob_store: BlobStore | None | object) -> BlobStore | None:
    """``None`` means no store; omit arg (Ellipsis) to resolve from env."""
    if blob_store is ...:
        return resolve_evidence_blob_store()
    return blob_store  # type: ignore[return-value]


def collect_metrics_for_incident(
    *,
    incident_id: UUID,
    start: float,
    end: float,
    query: str = _DEFAULT_PROM_QUERY,
    client: PrometheusClient | None = None,
    blob_store: BlobStore | None | object = ...,
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
        out = append_raw_evidence_with_blob(
            conn,
            incident_id=incident_id,
            kind="METRIC",
            fingerprint=fp,
            summary=summary,
            producer=producer,
            payload=payload,
            source="prometheus",
            external_ref={"window": {"start": start, "end": end}, "query": query},
            blob_store=_blob_store(blob_store),
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
    blob_store: BlobStore | None | object = ...,
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
        out = append_raw_evidence_with_blob(
            conn,
            incident_id=incident_id,
            kind="LOG",
            fingerprint=fp,
            summary=summary,
            producer=producer,
            payload=payload,
            source="loki",
            external_ref={"window": {"start": start, "end": end}, "query": query},
            blob_store=_blob_store(blob_store),
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
    blob_store: BlobStore | None | object = ...,
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
        out = append_raw_evidence_with_blob(
            conn,
            incident_id=incident_id,
            kind="TRACE",
            fingerprint=fp,
            summary=summary,
            producer=producer,
            payload=payload,
            source="tempo",
            external_ref={"window": {"start": start, "end": end}, "query": query},
            blob_store=_blob_store(blob_store),
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


def collect_changes_for_incident(
    *,
    incident_id: UUID,
    start: float,
    end: float,
    source: ChangeSource | None = None,
    service: str | None = None,
) -> list[CollectResult]:
    """Upsert Change rows then emit CHANGE Evidence via ``change_collector`` (G9)."""
    start, end = _clamp_window(start, end)
    since = datetime.fromtimestamp(start, tz=UTC)
    until = datetime.fromtimestamp(end, tz=UTC)
    change_source = source or SimChangeSource()
    changes = change_source.list_changes(service=service, since=since, until=until)
    producer = "change_collector"
    results: list[CollectResult] = []
    with connect() as conn:
        for ch in changes:
            upsert = upsert_change_command(
                conn,
                change_type=ch.change_type,
                service_key=ch.service_key,
                observed_at=ch.observed_at,
                source_ref=ch.source_ref,
                source=ch.source,
                fingerprint=ch.fingerprint,
                summary=ch.summary,
                payload=ch.payload,
                provenance=ch.provenance,
                commit=False,
            )
            fp = f"{producer}:{ch.fingerprint}"
            summary = f"{ch.change_type} {ch.service_key} {ch.source_ref}"
            out = append_evidence_command(
                conn,
                incident_id=incident_id,
                kind="CHANGE",
                fingerprint=fp,
                summary=summary,
                producer=producer,
                payload={
                    "change_id": str(upsert.change_id),
                    "change_key": upsert.change_key,
                    "change_type": ch.change_type,
                    "service_key": ch.service_key,
                    "source_ref": ch.source_ref,
                    "source": ch.source,
                    "change_fingerprint": ch.fingerprint,
                    **(ch.payload or {}),
                },
                provenance={
                    "layer": "RAW",
                    "quality": "MEDIUM",
                    "source": ch.source,
                    "change_id": str(upsert.change_id),
                    "external_ref": ch.source_ref,
                },
                observed_at=ch.observed_at,
                commit=False,
            )
            results.append(
                CollectResult(
                    kind="CHANGE",
                    producer=producer,
                    evidence_id=out.evidence_id,
                    fingerprint=fp,
                    inserted=out.inserted,
                    summary=summary,
                )
            )
        conn.commit()
    return results


def collect_incident_window(
    *,
    incident_id: UUID,
    start: float | None = None,
    end: float | None = None,
    metrics_query: str = _DEFAULT_PROM_QUERY,
    logs_query: str = _DEFAULT_LOKI_QUERY,
    traces_query: str = _DEFAULT_TEMPO_QUERY,
    blob_store: BlobStore | None | object = ...,
    change_source: ChangeSource | None = None,
) -> list[CollectResult]:
    """Collect METRIC + LOG + TRACE + CHANGE for an incident time window."""
    now = datetime.now(tz=UTC).timestamp()
    end_ts = end if end is not None else now
    start_ts = start if start is not None else end_ts - 900
    start_ts, end_ts = _clamp_window(start_ts, end_ts)
    store = _blob_store(blob_store)
    return [
        collect_metrics_for_incident(
            incident_id=incident_id,
            start=start_ts,
            end=end_ts,
            query=metrics_query,
            blob_store=store,
        ),
        collect_logs_for_incident(
            incident_id=incident_id,
            start=start_ts,
            end=end_ts,
            query=logs_query,
            blob_store=store,
        ),
        collect_traces_for_incident(
            incident_id=incident_id,
            start=start_ts,
            end=end_ts,
            query=traces_query,
            blob_store=store,
        ),
        *collect_changes_for_incident(
            incident_id=incident_id,
            start=start_ts,
            end=end_ts,
            source=change_source,
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
