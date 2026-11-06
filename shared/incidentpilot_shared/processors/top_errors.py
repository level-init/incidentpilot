"""Top error grouping processor — DETERMINISTIC_DERIVED (G4)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

RULE_TOP_ERRORS = "top_errors.v1"

_NORMALIZE = re.compile(r"\b\d+\b")


@dataclass(frozen=True, slots=True)
class TopErrorsResult:
    quality_rule_id: str
    summary: str
    payload: dict[str, Any]
    kind: str = "OTHER"


def _normalize_line(line: str) -> str:
    text = line.strip().lower()
    text = _NORMALIZE.sub("<n>", text)
    return text[:200]


def top_errors(
    log_payload: dict[str, Any],
    *,
    limit: int = 5,
) -> TopErrorsResult | None:
    """Group Loki-like log lines into top error patterns."""
    streams = log_payload.get("streams") or []
    if not isinstance(streams, list) or not streams:
        return None

    counts: Counter[str] = Counter()
    samples: dict[str, str] = {}
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        for pair in stream.get("values") or []:
            if not isinstance(pair, list | tuple) or len(pair) < 2:
                continue
            raw = str(pair[1])
            key = _normalize_line(raw)
            if not key:
                continue
            counts[key] += 1
            samples.setdefault(key, raw[:300])

    if not counts:
        return None

    top = counts.most_common(limit)
    groups = [
        {"pattern": pattern, "count": count, "sample": samples[pattern]}
        for pattern, count in top
    ]
    summary = f"top_errors: {len(groups)} patterns (top count={groups[0]['count']})"
    return TopErrorsResult(
        quality_rule_id=RULE_TOP_ERRORS,
        summary=summary,
        payload={
            "rule": RULE_TOP_ERRORS,
            "groups": groups,
            "source_query": log_payload.get("query"),
        },
    )
