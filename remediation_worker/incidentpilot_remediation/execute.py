"""Privileged execute path: VerifyExecutionAttempt → reconcile → execute (J1/J2)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from incidentpilot_adapters.remediation import (
    RECONCILE_APPLIED,
    RECONCILE_NOT_APPLIED,
    RECONCILE_PARTIAL,
    RECONCILE_UNKNOWN,
    BlindRetryForbidden,
    RemediationAdapter,
    RemediationResult,
    execute_verified,
    reconcile_verified,
    request_from_verified,
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

    Prefer :func:`verify_reconcile_and_execute` for ROLLBACK_DEPLOYMENT (J2) so
    lost-ACK retries reconcile first and never blind-retry on UNKNOWN/PARTIAL.
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


def verify_reconcile_and_execute(
    conn: Connection,
    adapter: RemediationAdapter,
    *,
    attempt_id: UUID,
    parameters: dict | None = None,
    action_id: UUID | None = None,
    action_version: int | None = None,
    action_type: str | None = None,
) -> tuple[VerifiedExecution, RemediationResult]:
    """J2 path: verify → reconcile → execute only when NOT_APPLIED.

    - ``APPLIED`` → skip execute (lost-ACK safe; no double-apply)
    - ``NOT_APPLIED`` → execute, then reconcile
    - ``UNKNOWN`` / ``PARTIAL`` → ``BlindRetryForbidden`` (no blind full retry)
    """
    verified = verify_execution_attempt(
        conn,
        attempt_id=attempt_id,
        parameters=parameters,
        action_id=action_id,
        action_version=action_version,
        action_type=action_type,
    )
    if verified is None:  # pragma: no cover
        raise UnverifiedExecutionError("verification returned no result")

    observed = reconcile_verified(adapter, verified)
    state = observed.reconciliation_state

    if state == RECONCILE_APPLIED:
        return verified, RemediationResult(
            ok=True,
            summary=observed.summary,
            adapter_result=dict(observed.adapter_result),
            reconciliation_state=RECONCILE_APPLIED,
            skipped_execute=True,
        )

    if state in {RECONCILE_UNKNOWN, RECONCILE_PARTIAL}:
        raise BlindRetryForbidden(
            f"reconcile={state}: refuse blind full retry for attempt {attempt_id}"
        )

    if state != RECONCILE_NOT_APPLIED:
        raise BlindRetryForbidden(
            f"reconcile={state!r}: refuse execute without NOT_APPLIED"
        )

    # Mutate may raise (e.g. LostAckError) after landing — caller retries via
    # this same entrypoint so reconcile observes APPLIED and skips re-execute.
    execute_verified(adapter, verified)
    final = reconcile_verified(adapter, verified)
    if final.reconciliation_state in {RECONCILE_UNKNOWN, RECONCILE_PARTIAL}:
        raise BlindRetryForbidden(
            f"post-execute reconcile={final.reconciliation_state}: no blind retry"
        )
    # Attach request identity for callers/tests without re-reading SoR.
    _ = request_from_verified(verified)
    return verified, RemediationResult(
        ok=final.ok and final.reconciliation_state == RECONCILE_APPLIED,
        summary=final.summary,
        adapter_result=dict(final.adapter_result),
        error_summary=final.error_summary,
        reconciliation_state=final.reconciliation_state,
        skipped_execute=False,
    )
