"""Deterministic post-remediation validation criteria (J7).

LLM may explain ValidationResult; it never chooses the outcome.
Checkout recovery thresholds are documented in ``docs/validation.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RULE_CHECKOUT_RECOVERY = "checkout_recovery.v1"

# Documented thresholds (docs/validation.md / docs/sim-baseline.md).
ERROR_RATE_MAX = 0.05
BASELINE_RATIO_MAX = 2.0

OUTCOME_RECOVERED = "RECOVERED"
OUTCOME_STILL_DEGRADED = "STILL_DEGRADED"
OUTCOME_UNKNOWN = "UNKNOWN"
OUTCOME_FAILED_VALIDATION = "FAILED_VALIDATION"


@dataclass(frozen=True, slots=True)
class ValidationCriteriaVerdict:
    quality_rule_id: str
    outcome: str
    reason: str
    criteria: dict[str, Any]
    observations: dict[str, Any]


def _extract_error_rate(payload: dict[str, Any]) -> float | None:
    if "error_rate" in payload:
        try:
            return float(payload["error_rate"])
        except (TypeError, ValueError):
            return None
    if "value" in payload:
        try:
            return float(payload["value"])
        except (TypeError, ValueError):
            return None
    # Prometheus-like series: use latest sample of first series.
    series = payload.get("series")
    if isinstance(series, list) and series:
        first = series[0]
        if isinstance(first, dict):
            values = first.get("values") or []
            if values:
                pair = values[-1]
                if isinstance(pair, list | tuple) and len(pair) >= 2:
                    try:
                        return float(pair[1])
                    except (TypeError, ValueError):
                        return None
    return None


def _baseline_breached(payload: dict[str, Any], *, ratio_max: float) -> bool | None:
    """Return True/False if derived baseline_compare present; else None."""
    if payload.get("rule") == "baseline_compare.v1" or "comparisons" in payload:
        comparisons = payload.get("comparisons") or []
        if not comparisons:
            return None
        return any(bool(c.get("breached")) for c in comparisons if isinstance(c, dict))
    ratio = payload.get("ratio")
    if ratio is not None:
        try:
            return float(ratio) >= ratio_max
        except (TypeError, ValueError):
            return None
    return None


def evaluate_checkout_recovery(
    *,
    metric_rows: list[dict[str, Any]],
    action_result_present: bool,
    error_rate_max: float = ERROR_RATE_MAX,
    baseline_ratio_max: float = BASELINE_RATIO_MAX,
) -> ValidationCriteriaVerdict:
    """Map METRIC (+ optional derived) Evidence to a ValidationResult outcome.

    ``metric_rows`` entries: ``id``, ``fingerprint``, ``payload`` (dict).
    """
    criteria = {
        "rule": RULE_CHECKOUT_RECOVERY,
        "error_rate_max": error_rate_max,
        "baseline_ratio_max": baseline_ratio_max,
        "require_action_result": True,
        "require_metric": True,
        "window_default_seconds": 15 * 60,
    }
    cited: list[str] = []
    rates: list[float] = []
    baseline_hit: bool | None = None

    for row in metric_rows:
        eid = str(row.get("id") or row.get("evidence_id") or "")
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if eid:
            cited.append(eid)
        rate = _extract_error_rate(payload)
        if rate is not None:
            rates.append(rate)
        breached = _baseline_breached(payload, ratio_max=baseline_ratio_max)
        if breached is not None:
            baseline_hit = bool(baseline_hit) or breached

    observations: dict[str, Any] = {
        "metric_evidence_ids": cited,
        "error_rates": rates,
        "baseline_breached": baseline_hit,
        "action_result_present": action_result_present,
    }

    if not action_result_present:
        return ValidationCriteriaVerdict(
            quality_rule_id=RULE_CHECKOUT_RECOVERY,
            outcome=OUTCOME_UNKNOWN,
            reason="ACTION_RESULT Evidence required before validation (J6)",
            criteria=criteria,
            observations=observations,
        )

    if not rates and baseline_hit is None:
        return ValidationCriteriaVerdict(
            quality_rule_id=RULE_CHECKOUT_RECOVERY,
            outcome=OUTCOME_UNKNOWN,
            reason="insufficient METRIC Evidence in validation window",
            criteria=criteria,
            observations=observations,
        )

    worst_rate = max(rates) if rates else None
    observations["worst_error_rate"] = worst_rate

    if baseline_hit is True:
        return ValidationCriteriaVerdict(
            quality_rule_id=RULE_CHECKOUT_RECOVERY,
            outcome=OUTCOME_STILL_DEGRADED,
            reason=f"baseline_compare breached (ratio≥{baseline_ratio_max:g})",
            criteria=criteria,
            observations=observations,
        )

    if worst_rate is not None and worst_rate > error_rate_max:
        return ValidationCriteriaVerdict(
            quality_rule_id=RULE_CHECKOUT_RECOVERY,
            outcome=OUTCOME_STILL_DEGRADED,
            reason=f"error_rate {worst_rate:.4f} > max {error_rate_max:.4f}",
            criteria=criteria,
            observations=observations,
        )

    if worst_rate is not None and worst_rate <= error_rate_max:
        return ValidationCriteriaVerdict(
            quality_rule_id=RULE_CHECKOUT_RECOVERY,
            outcome=OUTCOME_RECOVERED,
            reason=f"error_rate {worst_rate:.4f} ≤ max {error_rate_max:.4f}",
            criteria=criteria,
            observations=observations,
        )

    # Baseline clean but no numeric rate — treat as recovered when ACTION_RESULT exists.
    if baseline_hit is False:
        return ValidationCriteriaVerdict(
            quality_rule_id=RULE_CHECKOUT_RECOVERY,
            outcome=OUTCOME_RECOVERED,
            reason="baseline_compare clean; no error_rate series",
            criteria=criteria,
            observations=observations,
        )

    return ValidationCriteriaVerdict(
        quality_rule_id=RULE_CHECKOUT_RECOVERY,
        outcome=OUTCOME_UNKNOWN,
        reason="unable to evaluate checkout recovery from available Evidence",
        criteria=criteria,
        observations=observations,
    )
