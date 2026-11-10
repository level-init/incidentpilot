"""Sim ROLLBACK_DEPLOYMENT + reconcile (J2).

In-memory deployment revisions for local / fault+rollback tests. Idempotency key
is ``execution_attempt_id`` — a lost ACK after a successful mutate must not
double-apply on retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from incidentpilot_adapters.remediation.protocol import (
    RECONCILE_APPLIED,
    RECONCILE_NOT_APPLIED,
    RECONCILE_PARTIAL,
    RECONCILE_UNKNOWN,
    RemediationRequest,
    RemediationResult,
)


class LostAckError(RuntimeError):
    """Simulated lost response after mutate already landed (J2 lost-ACK test)."""


@dataclass
class SimDeploymentWorld:
    """Shared sim cluster state (deployment → observed revision)."""

    revisions: dict[str, str] = field(default_factory=dict)
    apply_counts: dict[str, int] = field(default_factory=dict)
    applied_attempts: set[UUID] = field(default_factory=set)
    force_unknown: set[str] = field(default_factory=set)
    force_partial: set[str] = field(default_factory=set)
    # When set, next execute for that deployment mutates then raises LostAckError.
    lose_ack_once: set[str] = field(default_factory=set)

    def seed(self, deployment: str, revision: str) -> None:
        self.revisions[deployment] = revision

    def observe(self, deployment: str) -> str | None:
        return self.revisions.get(deployment)


def _deployment(params: dict[str, Any]) -> str:
    dep = params.get("deployment") or params.get("service")
    if not dep:
        raise ValueError("ROLLBACK_DEPLOYMENT requires parameters.deployment")
    return str(dep)


def _desired_revision(params: dict[str, Any]) -> str:
    rev = params.get("revision") or params.get("to_revision")
    if not rev:
        raise ValueError("ROLLBACK_DEPLOYMENT requires parameters.revision")
    return str(rev)


class SimRollbackAdapter:
    """Semantic rollback against :class:`SimDeploymentWorld`."""

    name = "sim_rollback"

    def __init__(self, world: SimDeploymentWorld | None = None) -> None:
        self.world = world or SimDeploymentWorld()
        self.execute_calls: list[RemediationRequest] = []
        self.reconcile_calls: list[RemediationRequest] = []

    def reconcile(self, request: RemediationRequest) -> RemediationResult:
        self.reconcile_calls.append(request)
        if request.action_type != "ROLLBACK_DEPLOYMENT":
            return RemediationResult(
                ok=False,
                summary=f"sim_rollback cannot reconcile {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        deployment = _deployment(request.parameters)
        desired = _desired_revision(request.parameters)

        if deployment in self.world.force_unknown:
            return RemediationResult(
                ok=False,
                summary=f"{deployment}: observe UNKNOWN",
                adapter_result={
                    "deployment": deployment,
                    "desired_revision": desired,
                },
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        if deployment in self.world.force_partial:
            return RemediationResult(
                ok=False,
                summary=f"{deployment}: PARTIAL — no blind full retry",
                adapter_result={
                    "deployment": deployment,
                    "desired_revision": desired,
                    "observed_revision": self.world.observe(deployment),
                },
                reconciliation_state=RECONCILE_PARTIAL,
            )

        observed = self.world.observe(deployment)
        if observed == desired:
            return RemediationResult(
                ok=True,
                summary=f"{deployment} at desired revision {desired}",
                adapter_result={
                    "deployment": deployment,
                    "desired_revision": desired,
                    "observed_revision": observed,
                    "apply_count": self.world.apply_counts.get(deployment, 0),
                },
                reconciliation_state=RECONCILE_APPLIED,
            )
        return RemediationResult(
            ok=True,
            summary=(
                f"{deployment} NOT_APPLIED "
                f"(observed={observed!r}, desired={desired!r})"
            ),
            adapter_result={
                "deployment": deployment,
                "desired_revision": desired,
                "observed_revision": observed,
                "apply_count": self.world.apply_counts.get(deployment, 0),
            },
            reconciliation_state=RECONCILE_NOT_APPLIED,
        )

    def execute(self, request: RemediationRequest) -> RemediationResult:
        self.execute_calls.append(request)
        if request.action_type != "ROLLBACK_DEPLOYMENT":
            return RemediationResult(
                ok=False,
                summary=f"sim_rollback cannot execute {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )

        deployment = _deployment(request.parameters)
        desired = _desired_revision(request.parameters)

        # Idempotent on attempt_id: already mutated for this attempt → no re-apply.
        if request.attempt_id in self.world.applied_attempts:
            observed = self.world.observe(deployment)
            return RemediationResult(
                ok=True,
                summary=f"{deployment}: already applied for attempt (no double-apply)",
                adapter_result={
                    "deployment": deployment,
                    "desired_revision": desired,
                    "observed_revision": observed,
                    "apply_count": self.world.apply_counts.get(deployment, 0),
                    "idempotent": True,
                },
                reconciliation_state=RECONCILE_APPLIED,
                skipped_execute=True,
            )

        # Semantic rollback: set observed revision to SoR desired (clears bad rev).
        self.world.revisions[deployment] = desired
        self.world.apply_counts[deployment] = (
            self.world.apply_counts.get(deployment, 0) + 1
        )
        self.world.applied_attempts.add(request.attempt_id)

        if deployment in self.world.lose_ack_once:
            self.world.lose_ack_once.discard(deployment)
            raise LostAckError(
                f"lost ACK after rollback of {deployment} to {desired} "
                f"(mutate already landed; reconcile must observe APPLIED)"
            )

        return RemediationResult(
            ok=True,
            summary=f"rolled back {deployment} → {desired}",
            adapter_result={
                "deployment": deployment,
                "desired_revision": desired,
                "observed_revision": desired,
                "apply_count": self.world.apply_counts[deployment],
            },
            reconciliation_state=RECONCILE_APPLIED,
        )
