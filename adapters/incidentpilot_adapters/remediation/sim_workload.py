"""Sim RESTART_WORKLOAD + SCALE_WORKLOAD adapters (J3).

Same RemediationAdapter contract as J2: reconcile states
``NOT_APPLIED`` / ``APPLIED`` / ``PARTIAL`` / ``UNKNOWN``; idempotency key is
``execution_attempt_id``; no blind full retry on UNKNOWN/PARTIAL.
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
from incidentpilot_adapters.remediation.sim_rollback import LostAckError


@dataclass
class SimWorkloadWorld:
    """Shared sim cluster state for restart + scale."""

    generations: dict[str, int] = field(default_factory=dict)
    replicas: dict[str, int] = field(default_factory=dict)
    restart_counts: dict[str, int] = field(default_factory=dict)
    scale_counts: dict[str, int] = field(default_factory=dict)
    applied_restart_attempts: set[UUID] = field(default_factory=set)
    applied_scale_attempts: set[UUID] = field(default_factory=set)
    force_unknown: set[str] = field(default_factory=set)
    force_partial: set[str] = field(default_factory=set)
    lose_ack_once: set[str] = field(default_factory=set)

    def seed(
        self,
        workload: str,
        *,
        generation: int = 1,
        replicas: int = 1,
    ) -> None:
        self.generations[workload] = int(generation)
        self.replicas[workload] = int(replicas)


def _workload(params: dict[str, Any], *, action: str) -> str:
    name = params.get("workload") or params.get("deployment") or params.get("service")
    if not name:
        raise ValueError(f"{action} requires parameters.workload")
    return str(name)


def _desired_replicas(params: dict[str, Any]) -> int:
    if "replicas" not in params:
        raise ValueError("SCALE_WORKLOAD requires parameters.replicas")
    return int(params["replicas"])


def _forced_state(
    world: SimWorkloadWorld,
    workload: str,
    *,
    desired: dict[str, Any],
) -> RemediationResult | None:
    if workload in world.force_unknown:
        return RemediationResult(
            ok=False,
            summary=f"{workload}: observe UNKNOWN",
            adapter_result={"workload": workload, **desired},
            reconciliation_state=RECONCILE_UNKNOWN,
        )
    if workload in world.force_partial:
        return RemediationResult(
            ok=False,
            summary=f"{workload}: PARTIAL — no blind full retry",
            adapter_result={
                "workload": workload,
                **desired,
                "observed_generation": world.generations.get(workload),
                "observed_replicas": world.replicas.get(workload),
            },
            reconciliation_state=RECONCILE_PARTIAL,
        )
    return None


class SimRestartAdapter:
    """Semantic restart against :class:`SimWorkloadWorld`."""

    name = "sim_restart"

    def __init__(self, world: SimWorkloadWorld | None = None) -> None:
        self.world = world or SimWorkloadWorld()
        self.execute_calls: list[RemediationRequest] = []
        self.reconcile_calls: list[RemediationRequest] = []

    def reconcile(self, request: RemediationRequest) -> RemediationResult:
        self.reconcile_calls.append(request)
        if request.action_type != "RESTART_WORKLOAD":
            return RemediationResult(
                ok=False,
                summary=f"sim_restart cannot reconcile {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        workload = _workload(request.parameters, action="RESTART_WORKLOAD")
        forced = _forced_state(self.world, workload, desired={})
        if forced is not None:
            return forced

        if request.attempt_id in self.world.applied_restart_attempts:
            return RemediationResult(
                ok=True,
                summary=f"{workload} restart APPLIED for attempt",
                adapter_result={
                    "workload": workload,
                    "observed_generation": self.world.generations.get(workload),
                    "restart_count": self.world.restart_counts.get(workload, 0),
                },
                reconciliation_state=RECONCILE_APPLIED,
            )
        return RemediationResult(
            ok=True,
            summary=f"{workload} restart NOT_APPLIED",
            adapter_result={
                "workload": workload,
                "observed_generation": self.world.generations.get(workload),
                "restart_count": self.world.restart_counts.get(workload, 0),
            },
            reconciliation_state=RECONCILE_NOT_APPLIED,
        )

    def execute(self, request: RemediationRequest) -> RemediationResult:
        self.execute_calls.append(request)
        if request.action_type != "RESTART_WORKLOAD":
            return RemediationResult(
                ok=False,
                summary=f"sim_restart cannot execute {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        workload = _workload(request.parameters, action="RESTART_WORKLOAD")

        if request.attempt_id in self.world.applied_restart_attempts:
            return RemediationResult(
                ok=True,
                summary=f"{workload}: restart already applied (no double-restart)",
                adapter_result={
                    "workload": workload,
                    "observed_generation": self.world.generations.get(workload),
                    "restart_count": self.world.restart_counts.get(workload, 0),
                    "idempotent": True,
                },
                reconciliation_state=RECONCILE_APPLIED,
                skipped_execute=True,
            )

        gen = self.world.generations.get(workload, 0) + 1
        self.world.generations[workload] = gen
        self.world.restart_counts[workload] = (
            self.world.restart_counts.get(workload, 0) + 1
        )
        self.world.applied_restart_attempts.add(request.attempt_id)

        if workload in self.world.lose_ack_once:
            self.world.lose_ack_once.discard(workload)
            raise LostAckError(
                f"lost ACK after restart of {workload} "
                f"(mutate already landed; reconcile must observe APPLIED)"
            )

        return RemediationResult(
            ok=True,
            summary=f"restarted {workload} → generation {gen}",
            adapter_result={
                "workload": workload,
                "observed_generation": gen,
                "restart_count": self.world.restart_counts[workload],
            },
            reconciliation_state=RECONCILE_APPLIED,
        )


class SimScaleAdapter:
    """Semantic scale against :class:`SimWorkloadWorld`."""

    name = "sim_scale"

    def __init__(self, world: SimWorkloadWorld | None = None) -> None:
        self.world = world or SimWorkloadWorld()
        self.execute_calls: list[RemediationRequest] = []
        self.reconcile_calls: list[RemediationRequest] = []

    def reconcile(self, request: RemediationRequest) -> RemediationResult:
        self.reconcile_calls.append(request)
        if request.action_type != "SCALE_WORKLOAD":
            return RemediationResult(
                ok=False,
                summary=f"sim_scale cannot reconcile {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        workload = _workload(request.parameters, action="SCALE_WORKLOAD")
        desired = _desired_replicas(request.parameters)
        forced = _forced_state(
            self.world, workload, desired={"desired_replicas": desired}
        )
        if forced is not None:
            return forced

        observed = self.world.replicas.get(workload)
        if observed == desired:
            return RemediationResult(
                ok=True,
                summary=f"{workload} at desired replicas {desired}",
                adapter_result={
                    "workload": workload,
                    "desired_replicas": desired,
                    "observed_replicas": observed,
                    "scale_count": self.world.scale_counts.get(workload, 0),
                },
                reconciliation_state=RECONCILE_APPLIED,
            )
        return RemediationResult(
            ok=True,
            summary=(
                f"{workload} NOT_APPLIED "
                f"(observed={observed!r}, desired={desired!r})"
            ),
            adapter_result={
                "workload": workload,
                "desired_replicas": desired,
                "observed_replicas": observed,
                "scale_count": self.world.scale_counts.get(workload, 0),
            },
            reconciliation_state=RECONCILE_NOT_APPLIED,
        )

    def execute(self, request: RemediationRequest) -> RemediationResult:
        self.execute_calls.append(request)
        if request.action_type != "SCALE_WORKLOAD":
            return RemediationResult(
                ok=False,
                summary=f"sim_scale cannot execute {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        workload = _workload(request.parameters, action="SCALE_WORKLOAD")
        desired = _desired_replicas(request.parameters)

        if request.attempt_id in self.world.applied_scale_attempts:
            return RemediationResult(
                ok=True,
                summary=f"{workload}: scale already applied (no double-scale)",
                adapter_result={
                    "workload": workload,
                    "desired_replicas": desired,
                    "observed_replicas": self.world.replicas.get(workload),
                    "scale_count": self.world.scale_counts.get(workload, 0),
                    "idempotent": True,
                },
                reconciliation_state=RECONCILE_APPLIED,
                skipped_execute=True,
            )

        self.world.replicas[workload] = desired
        self.world.scale_counts[workload] = self.world.scale_counts.get(workload, 0) + 1
        self.world.applied_scale_attempts.add(request.attempt_id)

        if workload in self.world.lose_ack_once:
            self.world.lose_ack_once.discard(workload)
            raise LostAckError(
                f"lost ACK after scale of {workload} → {desired} "
                f"(mutate already landed; reconcile must observe APPLIED)"
            )

        return RemediationResult(
            ok=True,
            summary=f"scaled {workload} → {desired}",
            adapter_result={
                "workload": workload,
                "desired_replicas": desired,
                "observed_replicas": desired,
                "scale_count": self.world.scale_counts[workload],
            },
            reconciliation_state=RECONCILE_APPLIED,
        )
