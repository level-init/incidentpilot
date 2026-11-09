"""Deterministic policy engine (I2).

SYSTEM-only EvaluatePolicy. AI never binds POLICY_EVAL. Decisions:
ALLOW_AUTONOMOUS | REQUIRE_APPROVAL | BLOCK. No emergency override.
Autonomy levels are a simple input here; I3 owns durable config.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RULE_POLICY_V1 = "policy_engine.v1"

DECISION_ALLOW = "ALLOW_AUTONOMOUS"
DECISION_REQUIRE = "REQUIRE_APPROVAL"
DECISION_BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class PolicyVerdict:
    quality_rule_id: str
    decision: str
    reason: str
    policy_key: str
    policy_version: str
    inputs: dict[str, Any]


def evaluate_policy(
    *,
    action_type: str,
    parameters: dict[str, Any] | None = None,
    autonomy_level: int = 2,
) -> PolicyVerdict:
    """Map action + autonomy level to an immutable decision band."""
    params = dict(parameters or {})
    level = int(autonomy_level)
    inputs: dict[str, Any] = {
        "rule": RULE_POLICY_V1,
        "action_type": action_type,
        "autonomy_level": level,
        "parameters_keys": sorted(params.keys()),
    }

    # Explicit force-block for tests / ops kill-switch (not an emergency override of BLOCK).
    if str(params.get("policy_force", "")).upper() == "BLOCK":
        return PolicyVerdict(
            quality_rule_id=RULE_POLICY_V1,
            decision=DECISION_BLOCK,
            reason="policy_force=BLOCK",
            policy_key="default",
            policy_version="v1",
            inputs=inputs,
        )

    if action_type == "OTHER":
        return PolicyVerdict(
            quality_rule_id=RULE_POLICY_V1,
            decision=DECISION_BLOCK,
            reason="OTHER action_type is blocked by default policy",
            policy_key="default",
            policy_version="v1",
            inputs=inputs,
        )

    if level <= 1:
        return PolicyVerdict(
            quality_rule_id=RULE_POLICY_V1,
            decision=DECISION_BLOCK,
            reason="autonomy level 1 is observe-only (remediation blocked)",
            policy_key="default",
            policy_version="v1",
            inputs=inputs,
        )

    if level == 2:
        return PolicyVerdict(
            quality_rule_id=RULE_POLICY_V1,
            decision=DECISION_REQUIRE,
            reason="autonomy level 2 requires human/harness approval",
            policy_key="default",
            policy_version="v1",
            inputs=inputs,
        )

    # Level 3+: autonomous only for well-known reversible remediations.
    if action_type == "ROLLBACK_DEPLOYMENT":
        return PolicyVerdict(
            quality_rule_id=RULE_POLICY_V1,
            decision=DECISION_ALLOW,
            reason="autonomy level 3 allows autonomous ROLLBACK_DEPLOYMENT",
            policy_key="default",
            policy_version="v1",
            inputs=inputs,
        )
    return PolicyVerdict(
        quality_rule_id=RULE_POLICY_V1,
        decision=DECISION_REQUIRE,
        reason=f"autonomy level {level}: {action_type} still requires approval",
        policy_key="default",
        policy_version="v1",
        inputs=inputs,
    )


def assert_not_blocked(decision: str | None) -> None:
    """BLOCK (or missing) must never proceed toward adapter execute."""
    if decision == DECISION_BLOCK:
        raise PermissionError("PolicyDecision is BLOCK; execution forbidden")
    if decision not in {DECISION_ALLOW, DECISION_REQUIRE}:
        raise PermissionError("no PolicyDecision permitting execution")
