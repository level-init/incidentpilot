"""Deterministic policy engine (I2/I7).

SYSTEM-only EvaluatePolicy. AI never binds POLICY_EVAL. Decisions:
ALLOW_AUTONOMOUS | REQUIRE_APPROVAL | BLOCK. No emergency override.
Autonomy levels are a simple input here; I3 owns durable config.
I7 supplies versioned ``policy_key`` / ``policy_version`` + optional body.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RULE_POLICY_V1 = "policy_engine.v1"

DECISION_ALLOW = "ALLOW_AUTONOMOUS"
DECISION_REQUIRE = "REQUIRE_APPROVAL"
DECISION_BLOCK = "BLOCK"

DEFAULT_POLICY_KEY = "default"
DEFAULT_POLICY_VERSION = "v1"
DEFAULT_POLICY_BODY: dict[str, Any] = {
    "engine": RULE_POLICY_V1,
    "block_action_types": ["OTHER"],
    "level3_autonomous_action_types": ["ROLLBACK_DEPLOYMENT"],
}


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
    policy_key: str = DEFAULT_POLICY_KEY,
    policy_version: str = DEFAULT_POLICY_VERSION,
    policy_body: dict[str, Any] | None = None,
) -> PolicyVerdict:
    """Map action + autonomy level to an immutable decision band."""
    params = dict(parameters or {})
    level = int(autonomy_level)
    body = dict(DEFAULT_POLICY_BODY)
    if policy_body:
        body.update(policy_body)
    block_types = {str(x) for x in body.get("block_action_types", ["OTHER"])}
    level3_types = {
        str(x) for x in body.get("level3_autonomous_action_types", ["ROLLBACK_DEPLOYMENT"])
    }
    quality_rule = str(body.get("engine") or RULE_POLICY_V1)
    inputs: dict[str, Any] = {
        "rule": quality_rule,
        "action_type": action_type,
        "autonomy_level": level,
        "parameters_keys": sorted(params.keys()),
        "policy_key": policy_key,
        "policy_version": policy_version,
    }

    # Explicit force-block for tests / ops kill-switch (not an emergency override of BLOCK).
    if str(params.get("policy_force", "")).upper() == "BLOCK":
        return PolicyVerdict(
            quality_rule_id=quality_rule,
            decision=DECISION_BLOCK,
            reason="policy_force=BLOCK",
            policy_key=policy_key,
            policy_version=policy_version,
            inputs=inputs,
        )

    if action_type in block_types:
        return PolicyVerdict(
            quality_rule_id=quality_rule,
            decision=DECISION_BLOCK,
            reason=f"{action_type} is blocked by policy {policy_key}/{policy_version}",
            policy_key=policy_key,
            policy_version=policy_version,
            inputs=inputs,
        )

    if level <= 1:
        return PolicyVerdict(
            quality_rule_id=quality_rule,
            decision=DECISION_BLOCK,
            reason="autonomy level 1 is observe-only (remediation blocked)",
            policy_key=policy_key,
            policy_version=policy_version,
            inputs=inputs,
        )

    if level == 2:
        return PolicyVerdict(
            quality_rule_id=quality_rule,
            decision=DECISION_REQUIRE,
            reason="autonomy level 2 requires human/harness approval",
            policy_key=policy_key,
            policy_version=policy_version,
            inputs=inputs,
        )

    # Level 3+: autonomous only for configured reversible remediations.
    if action_type in level3_types:
        return PolicyVerdict(
            quality_rule_id=quality_rule,
            decision=DECISION_ALLOW,
            reason=(
                f"autonomy level 3 allows autonomous {action_type} "
                f"under {policy_key}/{policy_version}"
            ),
            policy_key=policy_key,
            policy_version=policy_version,
            inputs=inputs,
        )
    return PolicyVerdict(
        quality_rule_id=quality_rule,
        decision=DECISION_REQUIRE,
        reason=f"autonomy level {level}: {action_type} still requires approval",
        policy_key=policy_key,
        policy_version=policy_version,
        inputs=inputs,
    )


def assert_not_blocked(decision: str | None) -> None:
    """BLOCK (or missing) must never proceed toward adapter execute."""
    if decision == DECISION_BLOCK:
        raise PermissionError("PolicyDecision is BLOCK; execution forbidden")
    if decision not in {DECISION_ALLOW, DECISION_REQUIRE}:
        raise PermissionError("no PolicyDecision permitting execution")


def assert_approval_satisfied(
    decision: str | None,
    *,
    approval_status: str | None,
) -> None:
    """REQUIRE_APPROVAL needs APPROVED/CONSUMED Approval before execute (I4).

    ALLOW_AUTONOMOUS skips approval. Callers still version-bind via
    ``assert_approval_authorizes`` / ``consume_approval_command``.
    """
    assert_not_blocked(decision)
    if decision == DECISION_ALLOW:
        return
    if approval_status not in {"APPROVED", "CONSUMED"}:
        raise PermissionError("PolicyDecision is REQUIRE_APPROVAL; execution needs Approval (I4)")
