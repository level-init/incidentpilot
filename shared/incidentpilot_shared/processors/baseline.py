"""Baseline compare processor — DETERMINISTIC_DERIVED (G4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RULE_BASELINE_COMPARE = "baseline_compare.v1"


@dataclass(frozen=True, slots=True)
class BaselineCompareResult:
    quality_rule_id: str
    summary: str
    payload: dict[str, Any]
    kind: str = "OTHER"


def baseline_compare(
    metric_payload: dict[str, Any],
    *,
    threshold_ratio: float = 2.0,
) -> BaselineCompareResult | None:
    """Compare latest samples vs series mean; return derived payload or None.

    Expects Prometheus-like ``series[].values`` as ``[[ts, \"value\"], ...]``.
    """
    series = metric_payload.get("series") or []
    if not isinstance(series, list) or not series:
        return None

    comparisons: list[dict[str, Any]] = []
    for item in series:
        if not isinstance(item, dict):
            continue
        values = item.get("values") or []
        nums: list[float] = []
        for pair in values:
            if not isinstance(pair, list | tuple) or len(pair) < 2:
                continue
            try:
                nums.append(float(pair[1]))
            except (TypeError, ValueError):
                continue
        if len(nums) < 2:
            continue
        baseline = sum(nums[:-1]) / len(nums[:-1])
        latest = nums[-1]
        ratio = (latest / baseline) if baseline != 0 else (float("inf") if latest else 0.0)
        comparisons.append(
            {
                "metric": item.get("metric") or {},
                "baseline_mean": baseline,
                "latest": latest,
                "ratio": ratio,
                "breached": bool(baseline != 0 and ratio >= threshold_ratio),
            }
        )

    if not comparisons:
        return None

    breached = [c for c in comparisons if c["breached"]]
    summary = (
        f"baseline_compare: {len(breached)}/{len(comparisons)} series breached "
        f"×{threshold_ratio:g}"
    )
    return BaselineCompareResult(
        quality_rule_id=RULE_BASELINE_COMPARE,
        summary=summary,
        payload={
            "rule": RULE_BASELINE_COMPARE,
            "threshold_ratio": threshold_ratio,
            "comparisons": comparisons,
            "source_query": metric_payload.get("query"),
        },
    )
