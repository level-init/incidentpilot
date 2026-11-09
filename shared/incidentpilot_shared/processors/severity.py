"""Incident severity rules — deterministic SYSTEM updater (H8).

Severity is not raw alert severity and not AI-authored. Inputs are a hint
(alert labels / prior), impact snapshot band, SLO burn signal, and service
criticality. AI may explain the result only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RULE_SEVERITY_FROM_SIGNALS = "severity_from_signals.v1"

_SEV_RANK: dict[str, int] = {"SEV1": 3, "SEV2": 2, "SEV3": 1, "SEV4": 0}
_RANK_SEV: dict[int, str] = {v: k for k, v in _SEV_RANK.items()}

_CRIT_RANK: dict[str, int] = {
    "CRITICAL": 3,
    "HIGH": 2,
    "MEDIUM": 1,
    "LOW": 0,
}


@dataclass(frozen=True, slots=True)
class SeverityDecision:
    quality_rule_id: str
    severity: str
    explanation: str
    inputs: dict[str, Any]


def normalize_severity(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if not text:
        return None
    # Alertmanager-style labels.
    aliases = {
        "CRITICAL": "SEV1",
        "FATAL": "SEV1",
        "ERROR": "SEV2",
        "WARNING": "SEV3",
        "WARN": "SEV3",
        "INFO": "SEV4",
        "PAGE": "SEV1",
    }
    if text in _SEV_RANK:
        return text
    return aliases.get(text)


def normalize_criticality(raw: str | None) -> str:
    if raw is None:
        return "MEDIUM"
    text = str(raw).strip().upper()
    return text if text in _CRIT_RANK else "MEDIUM"


def severity_from_slo(
    *,
    burn_rate: float | None,
    error_budget_remaining: float | None,
) -> str | None:
    """Map SLO burn signals to a severity band (absent → None)."""
    if burn_rate is None and error_budget_remaining is None:
        return None
    if error_budget_remaining is not None and error_budget_remaining <= 0.1:
        return "SEV1"
    if burn_rate is not None:
        if burn_rate >= 14.0:
            return "SEV1"
        if burn_rate >= 2.0:
            return "SEV2"
        return "SEV3"
    if error_budget_remaining is not None and error_budget_remaining <= 0.5:
        return "SEV2"
    return "SEV3"


def severity_from_signals(
    *,
    severity_hint: str | None = None,
    impact_severity: str | None = None,
    burn_rate: float | None = None,
    error_budget_remaining: float | None = None,
    criticality: str | None = "MEDIUM",
) -> SeverityDecision:
    """Worst-of signals, then criticality nudge (deterministic)."""
    hint = normalize_severity(severity_hint)
    impact = normalize_severity(impact_severity)
    slo = severity_from_slo(burn_rate=burn_rate, error_budget_remaining=error_budget_remaining)
    crit = normalize_criticality(criticality)

    candidates: list[tuple[str, str]] = []
    if hint is not None:
        candidates.append(("hint", hint))
    if impact is not None:
        candidates.append(("impact", impact))
    if slo is not None:
        candidates.append(("slo", slo))

    if not candidates:
        # No signals → criticality-only baseline.
        base = {"CRITICAL": "SEV2", "HIGH": "SEV2", "MEDIUM": "SEV3", "LOW": "SEV4"}[crit]
        return SeverityDecision(
            quality_rule_id=RULE_SEVERITY_FROM_SIGNALS,
            severity=base,
            explanation=f"No hint/impact/SLO signals; criticality={crit} → {base}",
            inputs={
                "rule": RULE_SEVERITY_FROM_SIGNALS,
                "severity_hint": severity_hint,
                "impact_severity": impact_severity,
                "burn_rate": burn_rate,
                "error_budget_remaining": error_budget_remaining,
                "criticality": crit,
                "candidates": {},
            },
        )

    worst_source, worst = max(candidates, key=lambda c: _SEV_RANK.get(c[1], 0))
    rank = _SEV_RANK[worst]
    # CRITICAL escalates one notch; LOW de-escalates one notch.
    if crit == "CRITICAL":
        rank = min(3, rank + 1)
    elif crit == "LOW":
        rank = max(0, rank - 1)
    severity = _RANK_SEV[rank]

    parts = [f"{src}={sev}" for src, sev in candidates]
    explanation = (
        f"worst({', '.join(parts)})={worst} via {worst_source}; criticality={crit} → {severity}"
    )
    return SeverityDecision(
        quality_rule_id=RULE_SEVERITY_FROM_SIGNALS,
        severity=severity,
        explanation=explanation,
        inputs={
            "rule": RULE_SEVERITY_FROM_SIGNALS,
            "severity_hint": hint,
            "impact_severity": impact,
            "slo_severity": slo,
            "burn_rate": burn_rate,
            "error_budget_remaining": error_budget_remaining,
            "criticality": crit,
            "worst_source": worst_source,
            "before_criticality": worst,
            "candidates": dict(candidates),
        },
    )
