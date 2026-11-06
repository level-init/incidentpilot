"""Tempo search / trace client (TRACE evidence source)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from incidentpilot_adapters.telemetry._http import get_json


@dataclass(frozen=True, slots=True)
class TempoQueryResult:
    query: str
    start: float
    end: float
    traces: list[dict[str, Any]]


class TempoClient:
    def __init__(self, base_url: str | None = None, *, timeout: float = 15.0) -> None:
        self.base_url = (base_url or os.environ.get("TEMPO_URL", "")).rstrip("/")
        self.timeout = timeout

    def search(
        self,
        query: str,
        *,
        start: float,
        end: float,
        limit: int = 20,
    ) -> TempoQueryResult:
        if not self.base_url:
            raise RuntimeError("TEMPO_URL is not configured")
        # Tempo HTTP search API (tags / q depending on version). Prefer `q`.
        data = get_json(
            f"{self.base_url}/api/search",
            params={
                "q": query,
                "start": int(start),
                "end": int(end),
                "limit": min(limit, 50),
            },
            timeout=self.timeout,
        )
        traces = list(data.get("traces") or data.get("Traces") or [])[:limit]
        # Keep payloads bounded — drop large nested fields if present.
        compact: list[dict[str, Any]] = []
        for item in traces:
            if not isinstance(item, dict):
                continue
            compact.append(
                {
                    "traceID": item.get("traceID") or item.get("traceId"),
                    "rootServiceName": item.get("rootServiceName"),
                    "rootTraceName": item.get("rootTraceName"),
                    "durationMs": item.get("durationMs"),
                    "startTimeUnixNano": item.get("startTimeUnixNano"),
                }
            )
        return TempoQueryResult(
            query=query,
            start=start,
            end=end,
            traces=compact,
        )
