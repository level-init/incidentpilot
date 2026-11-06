"""Temporal activities for telemetry collect (evidence-worker only)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from temporalio import activity

from incidentpilot_worker.collectors import (
    collect_logs_for_incident,
    collect_metrics_for_incident,
    collect_result_to_dict,
    collect_traces_for_incident,
)


@activity.defn(name="collect_prometheus_metrics")
def collect_prometheus_metrics(
    incident_id: str,
    start: float,
    end: float,
    query: str = "up",
) -> dict[str, Any]:
    result = collect_metrics_for_incident(
        incident_id=UUID(incident_id),
        start=start,
        end=end,
        query=query,
    )
    return collect_result_to_dict(result)


@activity.defn(name="collect_loki_logs")
def collect_loki_logs(
    incident_id: str,
    start: float,
    end: float,
    query: str = '{job=~".+"}',
) -> dict[str, Any]:
    result = collect_logs_for_incident(
        incident_id=UUID(incident_id),
        start=start,
        end=end,
        query=query,
    )
    return collect_result_to_dict(result)


@activity.defn(name="collect_tempo_traces")
def collect_tempo_traces(
    incident_id: str,
    start: float,
    end: float,
    query: str = "{}",
) -> dict[str, Any]:
    result = collect_traces_for_incident(
        incident_id=UUID(incident_id),
        start=start,
        end=end,
        query=query,
    )
    return collect_result_to_dict(result)
