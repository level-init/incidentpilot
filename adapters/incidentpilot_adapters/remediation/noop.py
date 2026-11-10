"""No-op / recording RemediationAdapter for tests (J1/J2)."""

from __future__ import annotations

from uuid import UUID

from incidentpilot_adapters.remediation.protocol import (
    RECONCILE_APPLIED,
    RECONCILE_NOT_APPLIED,
    RemediationAdapter,
    RemediationRequest,
    RemediationResult,
)
from incidentpilot_shared.remediation_verify import (
    VerifiedExecution,
    require_verified_execution,
)


class NoopRemediationAdapter:
    """Records execute/reconcile calls (used after VerifyExecutionAttempt)."""

    name = "noop"

    def __init__(self) -> None:
        self.calls: list[RemediationRequest] = []
        self.reconcile_calls: list[RemediationRequest] = []
        self._applied: set[UUID] = set()

    def execute(self, request: RemediationRequest) -> RemediationResult:
        self.calls.append(request)
        self._applied.add(request.attempt_id)
        return RemediationResult(
            ok=True,
            summary=f"noop executed {request.action_type}",
            adapter_result={"adapter": self.name, "action_type": request.action_type},
            reconciliation_state=RECONCILE_APPLIED,
        )

    def reconcile(self, request: RemediationRequest) -> RemediationResult:
        self.reconcile_calls.append(request)
        state = (
            RECONCILE_APPLIED
            if request.attempt_id in self._applied
            else RECONCILE_NOT_APPLIED
        )
        return RemediationResult(
            ok=True,
            summary=f"noop reconcile {state}",
            adapter_result={"adapter": self.name, "action_type": request.action_type},
            reconciliation_state=state,
        )


def request_from_verified(verified: VerifiedExecution) -> RemediationRequest:
    """Build adapter request exclusively from VerifyExecutionAttempt output."""
    require_verified_execution(verified)
    return RemediationRequest(
        attempt_id=verified.attempt_id,
        action_id=verified.action_id,
        action_version=verified.action_version,
        action_type=verified.action_type,
        parameters=dict(verified.parameters),
        target_ref=dict(verified.target_ref),
        incident_id=verified.incident_id,
    )


def execute_verified(
    adapter: RemediationAdapter,
    verified: VerifiedExecution,
) -> RemediationResult:
    """Only entry point remediation-worker should use for execute (J1)."""
    require_verified_execution(verified)
    return adapter.execute(request_from_verified(verified))


def reconcile_verified(
    adapter: RemediationAdapter,
    verified: VerifiedExecution,
) -> RemediationResult:
    """Reconcile using SoR-verified request only (J2)."""
    require_verified_execution(verified)
    return adapter.reconcile(request_from_verified(verified))
