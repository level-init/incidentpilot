"""Hypothesis confirmation rules by class (H10).

Causal confirmation is SYSTEM-only. ``ValidationResult=RECOVERED`` alone is
never enough — class-specific checks must also pass. Deploy-class requires
CHANGE evidence (bad deploy / rollback spine).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RULE_CONFIRMATION_V1 = "confirmation_rules.v1"

DEPLOY_HYPOTHESIS_CLASSES = frozenset(
    {
        "bad_deployment",
        "deployment",
        "deploy",
        "rollback_deployment",
    }
)


@dataclass(frozen=True, slots=True)
class ConfirmationSignals:
    hypothesis_status: str
    hypothesis_class: str | None
    validation_recovered: bool
    has_change_evidence: bool
    has_action_result_evidence: bool
    cited_evidence_count: int


@dataclass(frozen=True, slots=True)
class ConfirmationDecision:
    quality_rule_id: str
    confirm: bool
    write_caused_by: bool
    reason: str
    inputs: dict[str, Any]


def evaluate_confirmation_rules(signals: ConfirmationSignals) -> ConfirmationDecision:
    """Return whether SYSTEM may CONFIRM (+ optional CAUSED_BY)."""
    inputs: dict[str, Any] = {
        "rule": RULE_CONFIRMATION_V1,
        "hypothesis_status": signals.hypothesis_status,
        "hypothesis_class": signals.hypothesis_class,
        "validation_recovered": signals.validation_recovered,
        "has_change_evidence": signals.has_change_evidence,
        "has_action_result_evidence": signals.has_action_result_evidence,
        "cited_evidence_count": signals.cited_evidence_count,
    }
    cls = (signals.hypothesis_class or "").strip().lower() or None

    if signals.hypothesis_status != "LEADING":
        return ConfirmationDecision(
            quality_rule_id=RULE_CONFIRMATION_V1,
            confirm=False,
            write_caused_by=False,
            reason="hypothesis must be LEADING to CONFIRM",
            inputs=inputs,
        )

    if signals.cited_evidence_count < 1:
        return ConfirmationDecision(
            quality_rule_id=RULE_CONFIRMATION_V1,
            confirm=False,
            write_caused_by=False,
            reason="CONFIRM requires cited Evidence on the LEADING hypothesis",
            inputs=inputs,
        )

    if not signals.validation_recovered:
        return ConfirmationDecision(
            quality_rule_id=RULE_CONFIRMATION_V1,
            confirm=False,
            write_caused_by=False,
            reason="CONFIRM requires ValidationResult outcome RECOVERED",
            inputs=inputs,
        )

    # RECOVERED alone is insufficient — class rules add required signals.
    if cls in DEPLOY_HYPOTHESIS_CLASSES:
        if not signals.has_change_evidence:
            return ConfirmationDecision(
                quality_rule_id=RULE_CONFIRMATION_V1,
                confirm=False,
                write_caused_by=False,
                reason=(
                    "deploy-class CONFIRM requires CHANGE Evidence "
                    "(RECOVERED alone is insufficient)"
                ),
                inputs=inputs,
            )
        if not signals.has_action_result_evidence:
            return ConfirmationDecision(
                quality_rule_id=RULE_CONFIRMATION_V1,
                confirm=False,
                write_caused_by=False,
                reason=(
                    "deploy-class CONFIRM requires ACTION_RESULT Evidence "
                    "(rollback/remediation) in addition to RECOVERED"
                ),
                inputs=inputs,
            )
        return ConfirmationDecision(
            quality_rule_id=RULE_CONFIRMATION_V1,
            confirm=True,
            write_caused_by=True,
            reason="deploy-class rules satisfied (LEADING + CHANGE + ACTION_RESULT + RECOVERED)",
            inputs=inputs,
        )

    # Default class: need a second signal beyond recovery (CHANGE or ACTION_RESULT).
    if not (signals.has_change_evidence or signals.has_action_result_evidence):
        return ConfirmationDecision(
            quality_rule_id=RULE_CONFIRMATION_V1,
            confirm=False,
            write_caused_by=False,
            reason=(
                "CONFIRM requires CHANGE or ACTION_RESULT Evidence "
                "in addition to RECOVERED (recovery alone is insufficient)"
            ),
            inputs=inputs,
        )

    return ConfirmationDecision(
        quality_rule_id=RULE_CONFIRMATION_V1,
        confirm=True,
        write_caused_by=signals.has_change_evidence,
        reason="class rules satisfied (LEADING + recovery + supporting Evidence)",
        inputs=inputs,
    )
