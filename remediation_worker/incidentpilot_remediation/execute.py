"""Privileged execute path: VerifyExecutionAttempt → RemediationAdapter (J1)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from incidentpilot_adapters.remediation import (
    RemediationAdapter,
    RemediationResult,
    execute_verified,
)
from incidentpilot_shared.remediation_verify import (
    UnverifiedExecutionError,
    VerifiedExecution,
    verify_execution_attempt,
)

if TYPE_CHECKING:
    from psycopg import Connection


def verify_and_execute(
    conn: Connection,
    adapter: RemediationAdapter,
    *,
    attempt_id: UUID,
    parameters: dict | None = None,
    action_id: UUID | None = None,
    action_version: int | None = None,
    action_type: str | None = None,
) -> tuple[VerifiedExecution, RemediationResult]:
    """J1 gate: verify SoR binding/params/policy, then adapter.execute.

    Never call ``adapter.execute`` without a successful verify — that is an
    ``UnverifiedExecutionError``.
    """
    verified = verify_execution_attempt(
        conn,
        attempt_id=attempt_id,
        parameters=parameters,
        action_id=action_id,
        action_version=action_version,
        action_type=action_type,
    )
    if verified is None:  # pragma: no cover — type narrowing
        raise UnverifiedExecutionError("verification returned no result")
    result = execute_verified(adapter, verified)
    return verified, result
