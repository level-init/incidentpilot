"""Privileged execute path: Verify → reconcile → execute → ACTION_RESULT (J1–J6)."""

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
from incidentpilot_shared.domain.commands import (
    AppendEvidenceResult,
    append_action_result_evidence_command,
)
from incidentpilot_shared.remediation_verify import (
    UnverifiedExecutionError,
    VerifiedExecution,
    verify_execution_attempt,
)

if TYPE_CHECKING:
    from psycopg import Connection


def _persist_action_result(
    conn: Connection,
    verified: VerifiedExecution,
    result: RemediationResult,
) -> AppendEvidenceResult:
    """SYSTEM Producer path — adapters never write Evidence (J6)."""
    return append_action_result_evidence_command(
        conn,
        incident_id=verified.incident_id,
        attempt_id=verified.attempt_id,
        action_id=verified.action_id,
        action_version=verified.action_version,
        action_type=verified.action_type,
        summary=result.summary,
        ok=result.ok,
        adapter_result=dict(result.adapter_result),
        error_summary=result.error_summary,
        reconciliation_state=result.reconciliation_state,
        skipped_execute=result.skipped_execute,
        parameters=dict(verified.parameters),
        commit=False,
    )


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

    Prefer :func:`verify_reconcile_and_execute` for semantic ops (J2+) so
    lost-ACK retries reconcile first and never blind-retry on UNKNOWN/PARTIAL.
    Persists ACTION_RESULT Evidence via Producer (J6).
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
    _persist_action_result(conn, verified, result)
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
    """J2+ path: verify → reconcile → execute only when NOT_APPLIED → Evidence.

    - ``APPLIED`` → skip execute (lost-ACK safe; no double-apply); still emit
      ACTION_RESULT (idempotent fingerprint)
    - ``NOT_APPLIED`` → execute, then reconcile, then ACTION_RESULT
    - ``UNKNOWN`` / ``PARTIAL`` → ``BlindRetryForbidden`` (no Evidence write)
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
        result = RemediationResult(
            ok=True,
            summary=observed.summary,
            adapter_result=dict(observed.adapter_result),
            reconciliation_state=RECONCILE_APPLIED,
            skipped_execute=True,
        )
        _persist_action_result(conn, verified, result)
        return verified, result

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
    result = RemediationResult(
        ok=final.ok and final.reconciliation_state == RECONCILE_APPLIED,
        summary=final.summary,
        adapter_result=dict(final.adapter_result),
        error_summary=final.error_summary,
        reconciliation_state=final.reconciliation_state,
        skipped_execute=False,
    )
    _persist_action_result(conn, verified, result)
    return verified, result
