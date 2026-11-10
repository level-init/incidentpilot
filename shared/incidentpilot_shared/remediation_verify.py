"""VerifyExecutionAttempt (J1) — SoR is authority; queue is not authorization.

Callers (remediation-worker) must verify an ``execution_attempt`` against the
immutable ``action_version`` snapshot before any RemediationAdapter.execute.
Claimed parameters that differ from SoR are rejected even when attempt_id is
real. Adapters never invent authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from incidentpilot_shared.processors.policy import (
    DECISION_ALLOW,
    DECISION_REQUIRE,
    assert_approval_satisfied,
    assert_not_blocked,
)

if TYPE_CHECKING:
    from psycopg import Connection


class ExecutionVerificationError(Exception):
    """Base class for failed VerifyExecutionAttempt."""


class AttemptNotFound(ExecutionVerificationError):
    pass


class AttemptNotReserved(ExecutionVerificationError):
    pass


class ParamMismatchError(ExecutionVerificationError):
    """Caller-claimed params do not exactly match SoR action_version."""


class BindingMismatchError(ExecutionVerificationError):
    """Caller-claimed action_id / version / type does not match the attempt."""


class UnverifiedExecutionError(ExecutionVerificationError):
    """Execute refused because VerifyExecutionAttempt did not succeed."""


@dataclass(frozen=True, slots=True)
class VerifiedExecution:
    """Authority-checked snapshot for adapter execute (SoR params only)."""

    attempt_id: UUID
    action_id: UUID
    action_version: int
    attempt_number: int
    attempt_state: str
    action_type: str
    parameters: dict[str, Any]
    target_ref: dict[str, Any]
    incident_id: UUID
    policy_decision: str
    policy_key: str | None
    policy_version: str | None
    approval_status: str | None


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def verify_execution_attempt(
    conn: Connection,
    *,
    attempt_id: UUID,
    parameters: dict[str, Any] | None = None,
    action_id: UUID | None = None,
    action_version: int | None = None,
    action_type: str | None = None,
) -> VerifiedExecution:
    """Verify attempt + exact SoR param match + policy/approval gates (J1).

    ``parameters`` / ``action_*`` are **claims** from the caller. Missing claims
    are filled from SoR; present claims must match exactly or raise.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ea.id, ea.action_id, ea.action_version, ea.attempt_number,
                   ea.state,
                   a.incident_id, a.action_type,
                   av.parameters, av.target_ref,
                   pd.decision, pd.policy_key, pd.policy_version,
                   ap.status AS approval_status
            FROM domain.execution_attempt ea
            JOIN domain.action a ON a.id = ea.action_id
            JOIN domain.action_version av
              ON av.action_id = ea.action_id AND av.version = ea.action_version
            LEFT JOIN domain.policy_decision pd
              ON pd.action_id = ea.action_id AND pd.action_version = ea.action_version
            LEFT JOIN domain.approval ap
              ON ap.action_id = ea.action_id AND ap.action_version = ea.action_version
            WHERE ea.id = %s
            """,
            (str(attempt_id),),
        )
        row = cur.fetchone()

    if row is None:
        raise AttemptNotFound(f"execution_attempt {attempt_id} not found")

    sor_action_id = UUID(str(row[1]))
    sor_version = int(row[2])
    attempt_number = int(row[3])
    attempt_state = str(row[4])
    incident_id = UUID(str(row[5]))
    sor_action_type = str(row[6])
    sor_params = row[7] if isinstance(row[7], dict) else json.loads(row[7] or "{}")
    sor_target = row[8] if isinstance(row[8], dict) else json.loads(row[8] or "{}")
    policy_decision = None if row[9] is None else str(row[9])
    policy_key = None if row[10] is None else str(row[10])
    policy_version = None if row[11] is None else str(row[11])
    approval_status = None if row[12] is None else str(row[12])

    if attempt_state != "RESERVED":
        raise AttemptNotReserved(
            f"execution_attempt {attempt_id} state is {attempt_state}, not RESERVED"
        )

    if action_id is not None and action_id != sor_action_id:
        raise BindingMismatchError(
            f"action_id mismatch: claimed {action_id}, SoR {sor_action_id}"
        )
    if action_version is not None and int(action_version) != sor_version:
        raise BindingMismatchError(
            f"action_version mismatch: claimed {action_version}, SoR {sor_version}"
        )
    if action_type is not None and str(action_type) != sor_action_type:
        raise BindingMismatchError(
            f"action_type mismatch: claimed {action_type}, SoR {sor_action_type}"
        )

    if parameters is not None:
        claimed = dict(parameters)
        if _canonical_json(claimed) != _canonical_json(sor_params):
            raise ParamMismatchError(
                "claimed parameters do not exactly match action_version SoR snapshot"
            )

    assert_not_blocked(policy_decision)
    assert_approval_satisfied(policy_decision, approval_status=approval_status)
    if policy_decision == DECISION_REQUIRE and approval_status not in {
        "APPROVED",
        "CONSUMED",
    }:
        # assert_approval_satisfied already covers this; keep explicit for clarity.
        raise ExecutionVerificationError(
            "REQUIRE_APPROVAL needs APPROVED/CONSUMED Approval before execute"
        )

    return VerifiedExecution(
        attempt_id=UUID(str(row[0])),
        action_id=sor_action_id,
        action_version=sor_version,
        attempt_number=attempt_number,
        attempt_state=attempt_state,
        action_type=sor_action_type,
        parameters=dict(sor_params),
        target_ref=dict(sor_target),
        incident_id=incident_id,
        policy_decision=str(policy_decision),
        policy_key=policy_key,
        policy_version=policy_version,
        approval_status=approval_status,
    )


def require_verified_execution(verified: VerifiedExecution | None) -> VerifiedExecution:
    """Refuse adapter execute when verification is missing (J1)."""
    if verified is None:
        raise UnverifiedExecutionError(
            "RemediationAdapter.execute refused: VerifyExecutionAttempt required"
        )
    if verified.policy_decision not in {DECISION_ALLOW, DECISION_REQUIRE}:
        raise UnverifiedExecutionError(
            f"RemediationAdapter.execute refused: policy {verified.policy_decision}"
        )
    return verified
