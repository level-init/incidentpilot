"""Hypothesis propose/rank helpers (H4).

SYSTEM commands own persistence. Scores are heuristics, never calibrated
probabilities. OPEN competing hypotheses map to status ``PROPOSED``.
"""

from __future__ import annotations

from typing import Any


def clamp_heuristic_score(score: float) -> float:
    return max(0.0, min(1.0, float(score)))


def heuristic_score_from_signals(
    *,
    citation_count: int,
    has_change_cite: bool = False,
    model_hint: float | None = None,
) -> float:
    """Deterministic heuristic (not a probability).

    Mixes citation richness, CHANGE-linked bonus, and optional AI hint.
    """
    base = min(0.55, 0.15 * max(0, citation_count))
    change_bonus = 0.2 if has_change_cite else 0.0
    hint = 0.0 if model_hint is None else 0.25 * clamp_heuristic_score(model_hint)
    return clamp_heuristic_score(base + change_bonus + hint)


def label_score_provenance(
    *,
    heuristic_score: float | None,
    source: str,
    ai_invocation_id: str | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "writer": "system",
        "score_kind": "heuristic",
        "source": source,
    }
    if heuristic_score is not None:
        meta["heuristic_score"] = float(heuristic_score)
    if ai_invocation_id is not None:
        meta["ai_invocation_id"] = ai_invocation_id
    return meta
