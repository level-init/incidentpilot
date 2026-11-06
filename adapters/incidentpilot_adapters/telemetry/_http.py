"""Minimal JSON GET helper (stdlib) — adapters stay dependency-light."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class TelemetryHttpError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def get_json(url: str, *, params: dict[str, Any], timeout: float = 15.0) -> Any:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    full = f"{url}?{query}" if query else url
    req = urllib.request.Request(full, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — local obs URLs
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise TelemetryHttpError(
            f"HTTP {exc.code} from {url}: {detail}", status=exc.code
        ) from exc
    except urllib.error.URLError as exc:
        raise TelemetryHttpError(f"request failed for {url}: {exc}") from exc
