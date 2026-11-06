"""Prometheus query_range client (METRIC evidence source)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from incidentpilot_adapters.telemetry._http import get_json


@dataclass(frozen=True, slots=True)
class PrometheusQueryResult:
    query: str
    start: float
    end: float
    step: str
    result_type: str
    series: list[dict[str, Any]]


class PrometheusClient:
    def __init__(self, base_url: str | None = None, *, timeout: float = 15.0) -> None:
        self.base_url = (base_url or os.environ.get("PROMETHEUS_URL", "")).rstrip("/")
        self.timeout = timeout

    def query_range(
        self,
        query: str,
        *,
        start: float,
        end: float,
        step: str = "30s",
        max_series: int = 20,
    ) -> PrometheusQueryResult:
        if not self.base_url:
            raise RuntimeError("PROMETHEUS_URL is not configured")
        data = get_json(
            f"{self.base_url}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
            timeout=self.timeout,
        )
        if data.get("status") != "success":
            raise RuntimeError(f"prometheus query failed: {data}")
        payload = data.get("data") or {}
        series = list(payload.get("result") or [])[:max_series]
        # Bound samples per series
        for item in series:
            values = item.get("values") or []
            if len(values) > 120:
                item["values"] = values[-120:]
        return PrometheusQueryResult(
            query=query,
            start=start,
            end=end,
            step=step,
            result_type=str(payload.get("resultType") or "matrix"),
            series=series,
        )
