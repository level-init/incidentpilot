"""RemediationAdapter contract (J1/J2).

Outbound only — adapters never write ``domain.*``. Execute payloads must come
from a successful ``verify_execution_attempt`` (SoR params), not from unverified
caller claims. Queue membership is not authorization.

J2 adds semantic reconcile: observe desired vs actual before mutate. States are
``NOT_APPLIED`` / ``APPLIED`` / ``PARTIAL`` / ``UNKNOWN``. Blind full retry on
``UNKNOWN`` or ``PARTIAL`` is forbidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

ReconciliationState = Literal["NOT_APPLIED", "APPLIED", "PARTIAL", "UNKNOWN"]

RECONCILE_NOT_APPLIED: ReconciliationState = "NOT_APPLIED"
RECONCILE_APPLIED: ReconciliationState = "APPLIED"
RECONCILE_PARTIAL: ReconciliationState = "PARTIAL"
RECONCILE_UNKNOWN: ReconciliationState = "UNKNOWN"


class BlindRetryForbidden(RuntimeError):
    """Execute refused: reconcile is UNKNOWN/PARTIAL — no blind full retry (J2)."""


@dataclass(frozen=True, slots=True)
class RemediationRequest:
    """Adapter input built from VerifiedExecution (SoR authority)."""

    attempt_id: UUID
    action_id: UUID
    action_version: int
    action_type: str
    parameters: dict[str, Any]
    target_ref: dict[str, Any] = field(default_factory=dict)
    incident_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RemediationResult:
    """Adapter outcome — domain persistence is the caller's job (J6)."""

    ok: bool
    summary: str
    adapter_result: dict[str, Any] = field(default_factory=dict)
    error_summary: str | None = None
    reconciliation_state: ReconciliationState | None = None
    skipped_execute: bool = False


class RemediationAdapter(Protocol):
    """Privileged execute/reconcile client used only by remediation-worker after verify."""

    name: str

    def execute(self, request: RemediationRequest) -> RemediationResult:
        """Perform the vendor/K8s/sim mutation. Never writes domain tables."""
        ...

    def reconcile(self, request: RemediationRequest) -> RemediationResult:
        """Observe desired vs actual without mutating. Never writes domain tables."""
        ...
