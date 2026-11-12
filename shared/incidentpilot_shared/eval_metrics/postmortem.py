"""Postmortem-stage metrics (N7) — grounding / unsupported claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from incidentpilot_shared.eval_metrics.engine import (
    AggregateResult,
    IncidentScoreInput,
    MetricResult,
    metric_invented_evidence_citations,
)


@dataclass(frozen=True)
class PostmortemScoreInput:
    """Facts from FINAL postmortem + incident evidence set."""

    postmortem_status: str
    corrective_actions_count: int
    # Citation ids on postmortem (evidence uuids / EV-keys) for invent check.
    known_evidence_ids: frozenset[str] = frozenset()
    cited_evidence_ids: frozenset[str] = frozenset()
    # Claims that failed citation validation at draft time (should be 0 on FINAL).
    unsupported_claim_count: int = 0
    claim_count: int = 0


def metric_postmortem_final(inp: PostmortemScoreInput) -> MetricResult:
    """Requires FINAL postmortem. Always applicable at this stage."""
    ok = inp.postmortem_status == "FINAL"
    return MetricResult(
        metric_id="postmortem_final",
        applicable=True,
        score=1.0 if ok else 0.0,
        hard_fail=not ok,
        detail={"status": inp.postmortem_status, "required": "FINAL"},
    )


def metric_corrective_actions_present(inp: PostmortemScoreInput) -> MetricResult:
    """FINAL postmortems must carry ≥1 corrective action (L5)."""
    ok = inp.corrective_actions_count >= 1
    return MetricResult(
        metric_id="corrective_actions_present",
        applicable=True,
        score=1.0 if ok else 0.0,
        hard_fail=not ok,
        detail={"count": inp.corrective_actions_count},
    )


def metric_unsupported_claims(inp: PostmortemScoreInput) -> MetricResult:
    """Hard-fail if any unsupported/uncited claims remain."""
    if inp.unsupported_claim_count > 0:
        return MetricResult(
            metric_id="unsupported_claims",
            applicable=True,
            score=0.0,
            hard_fail=True,
            detail={"unsupported_claim_count": inp.unsupported_claim_count},
        )
    return MetricResult(
        metric_id="unsupported_claims",
        applicable=True,
        score=1.0,
        hard_fail=False,
        detail={
            "unsupported_claim_count": 0,
            "claim_count": inp.claim_count,
        },
    )


def metric_postmortem_citations(inp: PostmortemScoreInput) -> MetricResult:
    """Reuse invented-citation hard-fail against postmortem cited_evidence_ids."""
    bridge = IncidentScoreInput(
        known_evidence_ids=inp.known_evidence_ids,
        cited_evidence_ids=inp.cited_evidence_ids,
    )
    base = metric_invented_evidence_citations(bridge)
    return MetricResult(
        metric_id="postmortem_invented_citations",
        applicable=base.applicable,
        score=base.score,
        hard_fail=base.hard_fail,
        detail=dict(base.detail),
    )


DEFAULT_POSTMORTEM_THRESHOLD = 0.7


def evaluate_postmortem(
    inp: PostmortemScoreInput,
    *,
    threshold: float = DEFAULT_POSTMORTEM_THRESHOLD,
) -> AggregateResult:
    """Aggregate postmortem-stage metrics (no LLM wording scores)."""
    metrics = (
        metric_postmortem_final(inp),
        metric_corrective_actions_present(inp),
        metric_unsupported_claims(inp),
        metric_postmortem_citations(inp),
    )
    hard = any(m.hard_fail for m in metrics)
    if hard:
        return AggregateResult(
            passed=False,
            hard_fail=True,
            score=0.0,
            threshold=threshold,
            metrics=metrics,
            summary={
                "reason": "hard_fail",
                "failed_metrics": [m.metric_id for m in metrics if m.hard_fail],
            },
        )
    scores = [float(m.score) for m in metrics if m.applicable and m.score is not None]
    agg = sum(scores) / len(scores) if scores else 1.0
    return AggregateResult(
        passed=agg >= threshold,
        hard_fail=False,
        score=agg,
        threshold=threshold,
        metrics=metrics,
        summary={
            "weighted_score": agg,
            "threshold": threshold,
            "stage": "postmortem",
        },
    )
