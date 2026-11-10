"""RemediationAdapter contract (J1).

Outbound only — adapters never write ``domain.*``. Execute payloads must come
from a successful ``verify_execution_attempt`` (SoR params), not from unverified
caller claims. Queue membership is not authorization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID


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


class RemediationAdapter(Protocol):
    """Privileged execute client used only by remediation-worker after verify."""

    name: str

    def execute(self, request: RemediationRequest) -> RemediationResult:
        """Perform the vendor/K8s/sim mutation. Never writes domain tables."""
        ...
