"""Sim PAUSE_CONSUMER + REROUTE_TRAFFIC (J5).

Queue-backlog / traffic-shift remediations. Reroute reconcile returns
``PARTIAL`` with ``observed_state`` when weights are mid-shift — never blind
full-retry. Same RemediationAdapter contract as J2–J4.
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


def _consumer_id(params: dict[str, Any]) -> str:
    name = (
        params.get("consumer")
        or params.get("queue")
        or params.get("workload")
        or params.get("service")
    )
    if not name:
        raise ValueError("PAUSE_CONSUMER requires parameters.consumer")
    return str(name)


def _desired_paused(params: dict[str, Any]) -> bool:
    if "paused" in params:
        return bool(params["paused"])
    # Default semantic for PAUSE_CONSUMER is pause=True.
    return True


def _route_service(params: dict[str, Any]) -> str:
    name = params.get("service") or params.get("service_key") or params.get("deployment")
    if not name:
        raise ValueError("REROUTE_TRAFFIC requires parameters.service")
    return str(name)


def _canonical_weights(weights: dict[str, Any]) -> dict[str, int]:
    return {str(k): int(v) for k, v in sorted(weights.items())}


def _desired_weights(params: dict[str, Any]) -> dict[str, int]:
    if "weights" in params and isinstance(params["weights"], dict):
        return _canonical_weights(params["weights"])
    target = params.get("target") or params.get("to") or params.get("destination")
    if not target:
        raise ValueError(
            "REROUTE_TRAFFIC requires parameters.weights or parameters.target"
        )
    percent = int(params.get("percent", params.get("weight_percent", 100)))
    if percent < 0 or percent > 100:
        raise ValueError("REROUTE_TRAFFIC percent must be 0..100")
    source = params.get("from") or params.get("source") or "primary"
    if str(source) == str(target):
        return _canonical_weights({str(target): 100})
    return _canonical_weights({str(source): 100 - percent, str(target): percent})


def _partial_progress(
    observed: dict[str, int],
    desired: dict[str, int],
    baseline: dict[str, int] | None,
) -> bool:
    """True when observed is neither baseline nor fully desired."""
    if observed == desired:
        return False
    if baseline is not None and observed == baseline:
        return False
    # Any destination weight that moved toward desired but not complete.
    keys = set(observed) | set(desired) | set(baseline or {})
    for key in keys:
        obs = observed.get(key, 0)
        des = desired.get(key, 0)
        base = (baseline or {}).get(key, 0)
        if obs != base and obs != des:
            return True
        if obs != base and des != base and obs != des:
            return True
    # Mid-shift: not equal baseline, not equal desired, and some overlap moved.
    if baseline is not None and observed != baseline and observed != desired:
        return True
    return False


@dataclass
class SimTrafficWorld:
    """In-memory consumer pause + traffic weight state."""

    paused: dict[str, bool] = field(default_factory=dict)
    routes: dict[str, dict[str, int]] = field(default_factory=dict)
    route_baselines: dict[str, dict[str, int]] = field(default_factory=dict)
    pause_counts: dict[str, int] = field(default_factory=dict)
    reroute_counts: dict[str, int] = field(default_factory=dict)
    applied_pause_attempts: set[UUID] = field(default_factory=set)
    applied_reroute_attempts: set[UUID] = field(default_factory=set)
    force_unknown: set[str] = field(default_factory=set)
    # Explicit PARTIAL inject (still must report observed_state).
    force_partial: set[str] = field(default_factory=set)
    lose_ack_once: set[str] = field(default_factory=set)

    def seed_consumer(self, consumer: str, *, paused: bool = False) -> None:
        self.paused[consumer] = paused

    def seed_route(
        self,
        service: str,
        weights: dict[str, int],
        *,
        as_baseline: bool = True,
    ) -> None:
        canonical = _canonical_weights(weights)
        self.routes[service] = dict(canonical)
        if as_baseline:
            self.route_baselines[service] = dict(canonical)

    def seed_queue_backlog_fault(self) -> None:
        """Catalog-aligned notification backlog starting point."""
        self.seed_consumer("notification-worker", paused=False)
        self.seed_route("notification", {"primary": 100, "drain": 0})

    def set_route_partial(self, service: str, weights: dict[str, int]) -> None:
        """Force mid-shift weights (for PARTIAL reconcile tests)."""
        self.routes[service] = _canonical_weights(weights)


class SimPauseConsumerAdapter:
    """PAUSE_CONSUMER against :class:`SimTrafficWorld`."""

    name = "sim_pause_consumer"

    def __init__(self, world: SimTrafficWorld | None = None) -> None:
        self.world = world or SimTrafficWorld()
        self.execute_calls: list[RemediationRequest] = []
        self.reconcile_calls: list[RemediationRequest] = []

    def reconcile(self, request: RemediationRequest) -> RemediationResult:
        self.reconcile_calls.append(request)
        if request.action_type != "PAUSE_CONSUMER":
            return RemediationResult(
                ok=False,
                summary=f"sim_pause_consumer cannot reconcile {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        consumer = _consumer_id(request.parameters)
        desired = _desired_paused(request.parameters)
        if consumer in self.world.force_unknown:
            return RemediationResult(
                ok=False,
                summary=f"{consumer}: observe UNKNOWN",
                adapter_result={
                    "consumer": consumer,
                    "observed_state": {"paused": self.world.paused.get(consumer)},
                },
                reconciliation_state=RECONCILE_UNKNOWN,
            )

        observed = self.world.paused.get(consumer)
        observed_state = {"consumer": consumer, "paused": observed}
        if observed == desired:
            return RemediationResult(
                ok=True,
                summary=f"{consumer} paused={desired}",
                adapter_result={
                    "consumer": consumer,
                    "desired_paused": desired,
                    "observed_state": observed_state,
                    "apply_count": self.world.pause_counts.get(consumer, 0),
                },
                reconciliation_state=RECONCILE_APPLIED,
            )
        return RemediationResult(
            ok=True,
            summary=f"{consumer} NOT_APPLIED (paused={observed!r}, desired={desired!r})",
            adapter_result={
                "consumer": consumer,
                "desired_paused": desired,
                "observed_state": observed_state,
                "apply_count": self.world.pause_counts.get(consumer, 0),
            },
            reconciliation_state=RECONCILE_NOT_APPLIED,
        )

    def execute(self, request: RemediationRequest) -> RemediationResult:
        self.execute_calls.append(request)
        if request.action_type != "PAUSE_CONSUMER":
            return RemediationResult(
                ok=False,
                summary=f"sim_pause_consumer cannot execute {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        consumer = _consumer_id(request.parameters)
        desired = _desired_paused(request.parameters)

        if request.attempt_id in self.world.applied_pause_attempts:
            return RemediationResult(
                ok=True,
                summary=f"{consumer}: pause already applied (no double-apply)",
                adapter_result={
                    "consumer": consumer,
                    "desired_paused": desired,
                    "observed_state": {
                        "consumer": consumer,
                        "paused": self.world.paused.get(consumer),
                    },
                    "apply_count": self.world.pause_counts.get(consumer, 0),
                    "idempotent": True,
                },
                reconciliation_state=RECONCILE_APPLIED,
                skipped_execute=True,
            )

        self.world.paused[consumer] = desired
        self.world.pause_counts[consumer] = self.world.pause_counts.get(consumer, 0) + 1
        self.world.applied_pause_attempts.add(request.attempt_id)

        if consumer in self.world.lose_ack_once:
            self.world.lose_ack_once.discard(consumer)
            raise LostAckError(
                f"lost ACK after pause of {consumer} "
                f"(mutate already landed; reconcile must observe APPLIED)"
            )

        return RemediationResult(
            ok=True,
            summary=f"set {consumer} paused={desired}",
            adapter_result={
                "consumer": consumer,
                "desired_paused": desired,
                "observed_state": {"consumer": consumer, "paused": desired},
                "apply_count": self.world.pause_counts[consumer],
            },
            reconciliation_state=RECONCILE_APPLIED,
        )


class SimRerouteTrafficAdapter:
    """REROUTE_TRAFFIC against :class:`SimTrafficWorld` (PARTIAL + observed_state)."""

    name = "sim_reroute_traffic"

    def __init__(self, world: SimTrafficWorld | None = None) -> None:
        self.world = world or SimTrafficWorld()
        self.execute_calls: list[RemediationRequest] = []
        self.reconcile_calls: list[RemediationRequest] = []

    def reconcile(self, request: RemediationRequest) -> RemediationResult:
        self.reconcile_calls.append(request)
        if request.action_type != "REROUTE_TRAFFIC":
            return RemediationResult(
                ok=False,
                summary=f"sim_reroute_traffic cannot reconcile {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        service = _route_service(request.parameters)
        desired = _desired_weights(request.parameters)
        observed = dict(self.world.routes.get(service) or {})
        baseline = self.world.route_baselines.get(service)
        observed_state = {
            "service": service,
            "weights": dict(observed),
            "baseline_weights": dict(baseline) if baseline is not None else None,
        }
        payload = {
            "service": service,
            "desired_weights": desired,
            "observed_state": observed_state,
            "apply_count": self.world.reroute_counts.get(service, 0),
        }

        if service in self.world.force_unknown:
            return RemediationResult(
                ok=False,
                summary=f"{service}: observe UNKNOWN",
                adapter_result=payload,
                reconciliation_state=RECONCILE_UNKNOWN,
            )

        if service in self.world.force_partial or _partial_progress(
            observed, desired, baseline
        ):
            return RemediationResult(
                ok=False,
                summary=f"{service}: PARTIAL traffic shift — no blind full retry",
                adapter_result=payload,
                reconciliation_state=RECONCILE_PARTIAL,
            )

        if observed == desired:
            return RemediationResult(
                ok=True,
                summary=f"{service} traffic at desired weights",
                adapter_result=payload,
                reconciliation_state=RECONCILE_APPLIED,
            )

        return RemediationResult(
            ok=True,
            summary=f"{service} NOT_APPLIED (weights={observed!r}, desired={desired!r})",
            adapter_result=payload,
            reconciliation_state=RECONCILE_NOT_APPLIED,
        )

    def execute(self, request: RemediationRequest) -> RemediationResult:
        self.execute_calls.append(request)
        if request.action_type != "REROUTE_TRAFFIC":
            return RemediationResult(
                ok=False,
                summary=f"sim_reroute_traffic cannot execute {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        service = _route_service(request.parameters)
        desired = _desired_weights(request.parameters)

        if request.attempt_id in self.world.applied_reroute_attempts:
            observed = dict(self.world.routes.get(service) or {})
            return RemediationResult(
                ok=True,
                summary=f"{service}: reroute already applied (no double-apply)",
                adapter_result={
                    "service": service,
                    "desired_weights": desired,
                    "observed_state": {"service": service, "weights": observed},
                    "apply_count": self.world.reroute_counts.get(service, 0),
                    "idempotent": True,
                },
                reconciliation_state=RECONCILE_APPLIED,
                skipped_execute=True,
            )

        self.world.routes[service] = dict(desired)
        self.world.reroute_counts[service] = (
            self.world.reroute_counts.get(service, 0) + 1
        )
        self.world.applied_reroute_attempts.add(request.attempt_id)
        # Clear forced partial once a full apply lands.
        self.world.force_partial.discard(service)

        if service in self.world.lose_ack_once:
            self.world.lose_ack_once.discard(service)
            raise LostAckError(
                f"lost ACK after reroute of {service} "
                f"(mutate already landed; reconcile must observe APPLIED)"
            )

        return RemediationResult(
            ok=True,
            summary=f"rerouted {service} → {desired!r}",
            adapter_result={
                "service": service,
                "desired_weights": desired,
                "observed_state": {"service": service, "weights": dict(desired)},
                "apply_count": self.world.reroute_counts[service],
            },
            reconciliation_state=RECONCILE_APPLIED,
        )
