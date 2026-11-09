"""Impact + SLO burn calculators — deterministic heuristics (H7).

Not Evidence authorship. Outputs are labeled ranges / heuristic severity for
demo credibility — not perfect revenue accounting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RULE_IMPACT_FROM_METRICS = "impact_from_metrics.v1"
RULE_SLO_BURN_FROM_METRICS = "slo_burn_from_metrics.v1"


@dataclass(frozen=True, slots=True)
class ImpactEstimate:
    quality_rule_id: str
    severity: str
    customer_impact_summary: str
    estimated_affected_users: int
    metrics: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SloBurnEstimate:
    quality_rule_id: str
    slo_key: str
    window_label: str
    burn_rate: float
    error_budget_remaining: float
    payload: dict[str, Any]


def _extract_numeric_samples(metric_payload: dict[str, Any]) -> list[float]:
    nums: list[float] = []
    # Simple single-value form (docs / tests).
    if "value" in metric_payload:
        try:
            nums.append(float(metric_payload["value"]))
        except (TypeError, ValueError):
            pass
    if "error_rate" in metric_payload:
        try:
            nums.append(float(metric_payload["error_rate"]))
        except (TypeError, ValueError):
            pass
    series = metric_payload.get("series") or []
    if isinstance(series, list):
        for item in series:
            if not isinstance(item, dict):
                continue
            values = item.get("values") or []
            for pair in values:
                if not isinstance(pair, list | tuple) or len(pair) < 2:
                    continue
                try:
                    nums.append(float(pair[1]))
                except (TypeError, ValueError):
                    continue
    return nums


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def impact_from_metrics(
    metric_payloads: list[dict[str, Any]],
    *,
    baseline_affected_users: int = 100,
) -> ImpactEstimate | None:
    """Map METRIC samples to a severity band + affected-user range."""
    samples: list[float] = []
    for payload in metric_payloads:
        if isinstance(payload, dict):
            samples.extend(_extract_numeric_samples(payload))
    if not samples:
        return None

    peak = max(samples)
    # Heuristic: treat values in [0,1] as error rates; larger as request rates.
    if peak <= 1.0:
        signal = peak
        users_lo = int(baseline_affected_users * (1 + 5 * signal))
        users_hi = int(baseline_affected_users * (1 + 20 * signal))
    else:
        signal = min(1.0, peak / (peak + baseline_affected_users))
        users_lo = int(peak * 0.5)
        users_hi = int(peak * 2.0)

    users_lo = max(1, users_lo)
    users_hi = max(users_lo, users_hi)
    mid = (users_lo + users_hi) // 2

    if signal >= 0.5 or peak >= 500:
        severity = "SEV1"
    elif signal >= 0.2 or peak >= 100:
        severity = "SEV2"
    else:
        severity = "SEV3"

    # Demo-only revenue label — not a ledger.
    revenue_lo = users_lo * 2
    revenue_hi = users_hi * 5

    return ImpactEstimate(
        quality_rule_id=RULE_IMPACT_FROM_METRICS,
        severity=severity,
        customer_impact_summary=(
            f"Heuristic impact from {len(samples)} metric samples "
            f"(peak={peak:g}) → ~{users_lo}–{users_hi} affected users"
        ),
        estimated_affected_users=mid,
        metrics={
            "rule": RULE_IMPACT_FROM_METRICS,
            "sample_count": len(samples),
            "peak": peak,
            "signal": signal,
            "affected_users_range": [users_lo, users_hi],
            "revenue_impact_usd_heuristic": {
                "range": [revenue_lo, revenue_hi],
                "accounting": "heuristic_not_ledger",
            },
        },
    )


def slo_burn_from_metrics(
    metric_payload: dict[str, Any],
    *,
    slo_key: str = "checkout_availability",
    window_label: str = "1h",
    slo_target: float = 0.999,
) -> SloBurnEstimate | None:
    """Estimate burn rate from an error-rate-like METRIC signal."""
    samples = _extract_numeric_samples(metric_payload)
    if not samples:
        return None
    latest = samples[-1]
    # If value looks like availability (near 1.0), convert to error rate.
    if latest > 1.0:
        error_rate = _clamp01(latest / (latest + 100.0))
    elif latest >= 0.9:
        error_rate = _clamp01(1.0 - latest)
    else:
        error_rate = _clamp01(latest)

    budget = max(1e-9, 1.0 - float(slo_target))
    burn_rate = error_rate / budget
    remaining = max(0.0, 1.0 - (error_rate / budget))

    return SloBurnEstimate(
        quality_rule_id=RULE_SLO_BURN_FROM_METRICS,
        slo_key=slo_key,
        window_label=window_label,
        burn_rate=float(burn_rate),
        error_budget_remaining=float(remaining),
        payload={
            "rule": RULE_SLO_BURN_FROM_METRICS,
            "slo_target": slo_target,
            "error_rate": error_rate,
            "latest_sample": latest,
            "formula": "burn_rate = error_rate / (1 - slo_target)",
        },
    )
