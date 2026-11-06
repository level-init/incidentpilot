"""Loki query_range client (LOG evidence source)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from incidentpilot_adapters.telemetry._http import get_json


@dataclass(frozen=True, slots=True)
class LokiQueryResult:
    query: str
    start_ns: int
    end_ns: int
    streams: list[dict[str, Any]]


class LokiClient:
    def __init__(self, base_url: str | None = None, *, timeout: float = 15.0) -> None:
        self.base_url = (base_url or os.environ.get("LOKI_URL", "")).rstrip("/")
        self.timeout = timeout

    def query_range(
        self,
        query: str,
        *,
        start: float,
        end: float,
        limit: int = 100,
        max_streams: int = 10,
    ) -> LokiQueryResult:
        if not self.base_url:
            raise RuntimeError("LOKI_URL is not configured")
        start_ns = int(start * 1_000_000_000)
        end_ns = int(end * 1_000_000_000)
        data = get_json(
            f"{self.base_url}/loki/api/v1/query_range",
            params={
                "query": query,
                "start": start_ns,
                "end": end_ns,
                "limit": min(limit, 200),
                "direction": "backward",
            },
            timeout=self.timeout,
        )
        if data.get("status") != "success":
            raise RuntimeError(f"loki query failed: {data}")
        payload = data.get("data") or {}
        streams = list(payload.get("result") or [])[:max_streams]
        for stream in streams:
            values = stream.get("values") or []
            if len(values) > limit:
                stream["values"] = values[:limit]
        return LokiQueryResult(
            query=query,
            start_ns=start_ns,
            end_ns=end_ns,
            streams=streams,
        )
