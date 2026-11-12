"""Deterministic operational metrics (N5).

No LLM wording / prose similarity scores. Invented evidence citations hard-fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RootCauseMatchSpec:
    """Answer-key match criteria from ``eval.ground_truth.match_spec.root_cause``."""

    service_keys: frozenset[str]
    change_types: frozenset[str] = frozenset()
    symptom_services: frozenset[str] = frozenset()
    expected_hypothesis_class: str | None = None


@dataclass(frozen=True)
class IncidentScoreInput:
    """Facts observed from IncidentPilot SoR for one scored window."""

    confirmed_hypothesis_class: str | None = None
    # Evidence ids that exist on the incident (uuid or EV- key strings).
    known_evidence_ids: frozenset[str] = frozenset()
    # Citations appearing on leading/confirmed hypotheses or postmortem claims.
    cited_evidence_ids: frozenset[str] = frozenset()
    observed_origin_service_keys: frozenset[str] = frozenset()
    observed_change_types: frozenset[str] = frozenset()
    executed_action_types: frozenset[str] = frozenset()
    severity: str | None = None


@dataclass(frozen=True)
class MetricResult:
    metric_id: str
    applicable: bool
    score: float | None  # 0.0–1.0 when applicable and not hard-failed alone
    hard_fail: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "applicable": self.applicable,
            "score": self.score,
            "hard_fail": self.hard_fail,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class AggregateResult:
    passed: bool
    hard_fail: bool
    score: float | None
    threshold: float
    metrics: tuple[MetricResult, ...]
    summary: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "hard_fail": self.hard_fail,
            "score": self.score,
            "threshold": self.threshold,
            "metrics": [m.as_dict() for m in self.metrics],
            "summary": dict(self.summary),
        }


def parse_root_cause_match_spec(
    match_spec: dict[str, Any] | None,
    *,
    expected_hypothesis_class: str | None = None,
    origin_service_keys: list[str] | tuple[str, ...] | None = None,
) -> RootCauseMatchSpec:
    """Build RootCauseMatchSpec from GT row fields + match_spec JSON."""
    ms = match_spec or {}
    rc = ms.get("root_cause") if isinstance(ms.get("root_cause"), dict) else {}
    services = rc.get("service_keys") or origin_service_keys or []
    changes = rc.get("change_types") or []
    symptoms = rc.get("symptom_services") or []
    hyp = expected_hypothesis_class or rc.get("hypothesis_class")
    return RootCauseMatchSpec(
        service_keys=frozenset(str(s) for s in services),
        change_types=frozenset(str(c) for c in changes),
        symptom_services=frozenset(str(s) for s in symptoms),
        expected_hypothesis_class=str(hyp) if hyp else None,
    )


def metric_invented_evidence_citations(inp: IncidentScoreInput) -> MetricResult:
    """Hard-fail when any citation is not in known evidence ids.

    Formula: invented = cited \\ known. If |invented| > 0 → hard_fail, score=0.
    Always applicable for operational evaluation.
    """
    invented = sorted(inp.cited_evidence_ids - inp.known_evidence_ids)
    if invented:
        return MetricResult(
            metric_id="invented_evidence_citations",
            applicable=True,
            score=0.0,
            hard_fail=True,
            detail={
                "invented_ids": invented,
                "cited_count": len(inp.cited_evidence_ids),
                "known_count": len(inp.known_evidence_ids),
            },
        )
    return MetricResult(
        metric_id="invented_evidence_citations",
        applicable=True,
        score=1.0,
        hard_fail=False,
        detail={
            "invented_ids": [],
            "cited_count": len(inp.cited_evidence_ids),
            "known_count": len(inp.known_evidence_ids),
        },
    )


def metric_root_cause_match(
    inp: IncidentScoreInput, spec: RootCauseMatchSpec
) -> MetricResult:
    """Service + hypothesis class overlap vs RootCauseMatchSpec.

    Applicability: spec.service_keys non-empty OR expected_hypothesis_class set.

    Score (equal weights among applicable parts):
    - class_match: 1 if confirmed_hypothesis_class == expected, else 0
      (skipped if expected_hypothesis_class is None)
    - service_recall: |observed ∩ expected| / |expected|
      (skipped if expected service_keys empty)
    - change_recall: |observed_change ∩ expected| / |expected|
      (skipped if expected change_types empty)

    Final = mean of applicable part scores.
    """
    parts: list[tuple[str, float]] = []
    detail: dict[str, Any] = {}

    if spec.expected_hypothesis_class:
        ok = inp.confirmed_hypothesis_class == spec.expected_hypothesis_class
        parts.append(("hypothesis_class", 1.0 if ok else 0.0))
        detail["hypothesis_class"] = {
            "expected": spec.expected_hypothesis_class,
            "observed": inp.confirmed_hypothesis_class,
            "match": ok,
        }

    if spec.service_keys:
        inter = inp.observed_origin_service_keys & spec.service_keys
        recall = len(inter) / len(spec.service_keys)
        parts.append(("service_recall", recall))
        detail["services"] = {
            "expected": sorted(spec.service_keys),
            "observed": sorted(inp.observed_origin_service_keys),
            "intersection": sorted(inter),
            "recall": recall,
        }

    if spec.change_types:
        inter_c = inp.observed_change_types & spec.change_types
        recall_c = len(inter_c) / len(spec.change_types)
        parts.append(("change_recall", recall_c))
        detail["change_types"] = {
            "expected": sorted(spec.change_types),
            "observed": sorted(inp.observed_change_types),
            "intersection": sorted(inter_c),
            "recall": recall_c,
        }

    if not parts:
        return MetricResult(
            metric_id="root_cause_match",
            applicable=False,
            score=None,
            detail={"reason": "empty RootCauseMatchSpec"},
        )

    score = sum(p[1] for p in parts) / len(parts)
    detail["parts"] = {name: val for name, val in parts}
    return MetricResult(
        metric_id="root_cause_match",
        applicable=True,
        score=score,
        detail=detail,
    )


def metric_action_type_match(
    inp: IncidentScoreInput,
    *,
    expected_action_types: frozenset[str],
) -> MetricResult:
    """Jaccard overlap of executed vs expected action types.

    Applicable when expected_action_types non-empty.
    score = |E ∩ O| / |E ∪ O| (1.0 if both empty — not applicable instead).
    """
    if not expected_action_types:
        return MetricResult(
            metric_id="action_type_match",
            applicable=False,
            score=None,
            detail={"reason": "no expected_action_types"},
        )
    union = expected_action_types | inp.executed_action_types
    inter = expected_action_types & inp.executed_action_types
    score = (len(inter) / len(union)) if union else 1.0
    return MetricResult(
        metric_id="action_type_match",
        applicable=True,
        score=score,
        detail={
            "expected": sorted(expected_action_types),
            "executed": sorted(inp.executed_action_types),
            "intersection": sorted(inter),
            "jaccard": score,
        },
    )


def metric_severity_match(
    inp: IncidentScoreInput, *, expected_severity: str | None
) -> MetricResult:
    """Exact severity match when GT declares expected_severity."""
    if not expected_severity:
        return MetricResult(
            metric_id="severity_match",
            applicable=False,
            score=None,
            detail={"reason": "no expected_severity"},
        )
    ok = inp.severity == expected_severity
    return MetricResult(
        metric_id="severity_match",
        applicable=True,
        score=1.0 if ok else 0.0,
        detail={
            "expected": expected_severity,
            "observed": inp.severity,
            "match": ok,
        },
    )


DEFAULT_PASS_THRESHOLD = 0.7

# Weights among applicable non-hard-fail scoring metrics.
_WEIGHTS = {
    "root_cause_match": 0.5,
    "action_type_match": 0.3,
    "severity_match": 0.2,
}


def evaluate_operational(
    inp: IncidentScoreInput,
    *,
    match_spec: RootCauseMatchSpec,
    expected_action_types: frozenset[str] | set[str] | list[str] = (),
    expected_severity: str | None = None,
    threshold: float = DEFAULT_PASS_THRESHOLD,
) -> AggregateResult:
    """Run operational metrics and aggregate.

    Aggregation:
    1. If any metric hard_fail → passed=False, score=0.
    2. Else weighted mean of applicable scoring metrics (weights renormalized).
    3. passed = aggregate_score >= threshold.
    invented_evidence_citations contributes hard_fail only (not in weighted mean
    when score=1; when hard_fail it short-circuits).
    """
    expected_actions = frozenset(str(a) for a in expected_action_types)
    metrics = (
        metric_invented_evidence_citations(inp),
        metric_root_cause_match(inp, match_spec),
        metric_action_type_match(inp, expected_action_types=expected_actions),
        metric_severity_match(inp, expected_severity=expected_severity),
    )

    hard = any(m.hard_fail for m in metrics)
    if hard:
        return AggregateResult(
            passed=False,
            hard_fail=True,
            score=0.0,
            threshold=threshold,
            metrics=metrics,
            summary={"reason": "hard_fail", "failed_metrics": [
                m.metric_id for m in metrics if m.hard_fail
            ]},
        )

    weighted: list[tuple[float, float]] = []  # (weight, score)
    for m in metrics:
        if not m.applicable or m.score is None:
            continue
        if m.metric_id == "invented_evidence_citations":
            continue  # binary gate already passed
        w = _WEIGHTS.get(m.metric_id, 0.0)
        if w > 0:
            weighted.append((w, float(m.score)))

    if not weighted:
        # Only citation gate applied and passed — treat as pass with score 1.
        agg = 1.0
    else:
        wsum = sum(w for w, _ in weighted)
        agg = sum(w * s for w, s in weighted) / wsum

    passed = agg >= threshold
    return AggregateResult(
        passed=passed,
        hard_fail=False,
        score=agg,
        threshold=threshold,
        metrics=metrics,
        summary={
            "weighted_score": agg,
            "threshold": threshold,
            "applicable_metrics": [
                m.metric_id for m in metrics if m.applicable
            ],
        },
    )
