"""Sim feature-flag disable/restore + config restore (J4).

Targets the bad-flag / bad-config scenario class (e.g. ``strict_jwt``,
``jwt_skew_seconds``, ``pool_size``). Same RemediationAdapter reconcile
contract as J2/J3.
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

_FLAG_ACTIONS = frozenset({"DISABLE_FEATURE_FLAG", "RESTORE_FEATURE_FLAG"})


def _flag_key(params: dict[str, Any]) -> str:
    flag = params.get("flag") or params.get("flag_key")
    if not flag:
        raise ValueError("feature-flag op requires parameters.flag")
    service = params.get("service") or params.get("service_key")
    if service:
        return f"{service}:{flag}"
    return str(flag)


def _config_key(params: dict[str, Any]) -> str:
    key = params.get("key") or params.get("config_key")
    if not key:
        raise ValueError("RESTORE_CONFIG requires parameters.key")
    service = params.get("service") or params.get("service_key")
    if service:
        return f"{service}:{key}"
    return str(key)


def _desired_flag_value(action_type: str, params: dict[str, Any]) -> Any:
    if action_type == "DISABLE_FEATURE_FLAG":
        if "value" in params:
            return params["value"]
        if "enabled" in params:
            return bool(params["enabled"])
        return False
    if "value" in params:
        return params["value"]
    if "enabled" in params:
        return bool(params["enabled"])
    raise ValueError("RESTORE_FEATURE_FLAG requires parameters.value (or enabled)")


def _desired_config_value(params: dict[str, Any]) -> Any:
    if "value" not in params:
        raise ValueError("RESTORE_CONFIG requires parameters.value")
    return params["value"]


@dataclass
class SimFlagConfigWorld:
    """In-memory flag + config state for sim faults."""

    flags: dict[str, Any] = field(default_factory=dict)
    configs: dict[str, Any] = field(default_factory=dict)
    flag_apply_counts: dict[str, int] = field(default_factory=dict)
    config_apply_counts: dict[str, int] = field(default_factory=dict)
    applied_flag_attempts: set[UUID] = field(default_factory=set)
    applied_config_attempts: set[UUID] = field(default_factory=set)
    force_unknown: set[str] = field(default_factory=set)
    force_partial: set[str] = field(default_factory=set)
    lose_ack_once: set[str] = field(default_factory=set)

    def seed_flag(
        self,
        flag: str,
        value: Any,
        *,
        service: str | None = None,
    ) -> None:
        key = f"{service}:{flag}" if service else str(flag)
        self.flags[key] = value

    def seed_config(
        self,
        key: str,
        value: Any,
        *,
        service: str | None = None,
    ) -> None:
        full = f"{service}:{key}" if service else str(key)
        self.configs[full] = value

    def seed_bad_flag_fault(self) -> None:
        """Catalog-aligned auth flag fault: ``strict_jwt=true``."""
        self.seed_flag("strict_jwt", True, service="auth")

    def seed_bad_config_faults(self) -> None:
        """Catalog-aligned config faults (auth skew + inventory pool)."""
        self.seed_config("jwt_skew_seconds", 0, service="auth")
        self.seed_config("pool_size", 4, service="inventory")


def _forced(
    world: SimFlagConfigWorld,
    resource_key: str,
    *,
    extra: dict[str, Any],
) -> RemediationResult | None:
    if resource_key in world.force_unknown:
        return RemediationResult(
            ok=False,
            summary=f"{resource_key}: observe UNKNOWN",
            adapter_result={"resource": resource_key, **extra},
            reconciliation_state=RECONCILE_UNKNOWN,
        )
    if resource_key in world.force_partial:
        return RemediationResult(
            ok=False,
            summary=f"{resource_key}: PARTIAL — no blind full retry",
            adapter_result={"resource": resource_key, **extra},
            reconciliation_state=RECONCILE_PARTIAL,
        )
    return None


class SimFeatureFlagAdapter:
    """DISABLE_FEATURE_FLAG + RESTORE_FEATURE_FLAG against sim world."""

    name = "sim_feature_flag"

    def __init__(self, world: SimFlagConfigWorld | None = None) -> None:
        self.world = world or SimFlagConfigWorld()
        self.execute_calls: list[RemediationRequest] = []
        self.reconcile_calls: list[RemediationRequest] = []

    def reconcile(self, request: RemediationRequest) -> RemediationResult:
        self.reconcile_calls.append(request)
        if request.action_type not in _FLAG_ACTIONS:
            return RemediationResult(
                ok=False,
                summary=f"sim_feature_flag cannot reconcile {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        key = _flag_key(request.parameters)
        desired = _desired_flag_value(request.action_type, request.parameters)
        forced = _forced(
            self.world, key, extra={"desired_value": desired, "kind": "flag"}
        )
        if forced is not None:
            return forced

        observed = self.world.flags.get(key)
        if observed == desired:
            return RemediationResult(
                ok=True,
                summary=f"flag {key} at desired {desired!r}",
                adapter_result={
                    "flag_key": key,
                    "desired_value": desired,
                    "observed_value": observed,
                    "apply_count": self.world.flag_apply_counts.get(key, 0),
                },
                reconciliation_state=RECONCILE_APPLIED,
            )
        return RemediationResult(
            ok=True,
            summary=f"flag {key} NOT_APPLIED (observed={observed!r}, desired={desired!r})",
            adapter_result={
                "flag_key": key,
                "desired_value": desired,
                "observed_value": observed,
                "apply_count": self.world.flag_apply_counts.get(key, 0),
            },
            reconciliation_state=RECONCILE_NOT_APPLIED,
        )

    def execute(self, request: RemediationRequest) -> RemediationResult:
        self.execute_calls.append(request)
        if request.action_type not in _FLAG_ACTIONS:
            return RemediationResult(
                ok=False,
                summary=f"sim_feature_flag cannot execute {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        key = _flag_key(request.parameters)
        desired = _desired_flag_value(request.action_type, request.parameters)

        if request.attempt_id in self.world.applied_flag_attempts:
            return RemediationResult(
                ok=True,
                summary=f"flag {key}: already applied for attempt (no double-apply)",
                adapter_result={
                    "flag_key": key,
                    "desired_value": desired,
                    "observed_value": self.world.flags.get(key),
                    "apply_count": self.world.flag_apply_counts.get(key, 0),
                    "idempotent": True,
                },
                reconciliation_state=RECONCILE_APPLIED,
                skipped_execute=True,
            )

        self.world.flags[key] = desired
        self.world.flag_apply_counts[key] = self.world.flag_apply_counts.get(key, 0) + 1
        self.world.applied_flag_attempts.add(request.attempt_id)

        if key in self.world.lose_ack_once:
            self.world.lose_ack_once.discard(key)
            raise LostAckError(
                f"lost ACK after flag mutate of {key} → {desired!r} "
                f"(mutate already landed; reconcile must observe APPLIED)"
            )

        verb = "disabled" if request.action_type == "DISABLE_FEATURE_FLAG" else "restored"
        return RemediationResult(
            ok=True,
            summary=f"{verb} flag {key} → {desired!r}",
            adapter_result={
                "flag_key": key,
                "desired_value": desired,
                "observed_value": desired,
                "apply_count": self.world.flag_apply_counts[key],
            },
            reconciliation_state=RECONCILE_APPLIED,
        )


class SimConfigRestoreAdapter:
    """RESTORE_CONFIG against sim world."""

    name = "sim_config_restore"

    def __init__(self, world: SimFlagConfigWorld | None = None) -> None:
        self.world = world or SimFlagConfigWorld()
        self.execute_calls: list[RemediationRequest] = []
        self.reconcile_calls: list[RemediationRequest] = []

    def reconcile(self, request: RemediationRequest) -> RemediationResult:
        self.reconcile_calls.append(request)
        if request.action_type != "RESTORE_CONFIG":
            return RemediationResult(
                ok=False,
                summary=f"sim_config_restore cannot reconcile {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        key = _config_key(request.parameters)
        desired = _desired_config_value(request.parameters)
        forced = _forced(
            self.world, key, extra={"desired_value": desired, "kind": "config"}
        )
        if forced is not None:
            return forced

        observed = self.world.configs.get(key)
        if observed == desired:
            return RemediationResult(
                ok=True,
                summary=f"config {key} at desired {desired!r}",
                adapter_result={
                    "config_key": key,
                    "desired_value": desired,
                    "observed_value": observed,
                    "apply_count": self.world.config_apply_counts.get(key, 0),
                },
                reconciliation_state=RECONCILE_APPLIED,
            )
        return RemediationResult(
            ok=True,
            summary=(
                f"config {key} NOT_APPLIED "
                f"(observed={observed!r}, desired={desired!r})"
            ),
            adapter_result={
                "config_key": key,
                "desired_value": desired,
                "observed_value": observed,
                "apply_count": self.world.config_apply_counts.get(key, 0),
            },
            reconciliation_state=RECONCILE_NOT_APPLIED,
        )

    def execute(self, request: RemediationRequest) -> RemediationResult:
        self.execute_calls.append(request)
        if request.action_type != "RESTORE_CONFIG":
            return RemediationResult(
                ok=False,
                summary=f"sim_config_restore cannot execute {request.action_type}",
                error_summary="unsupported_action_type",
                reconciliation_state=RECONCILE_UNKNOWN,
            )
        key = _config_key(request.parameters)
        desired = _desired_config_value(request.parameters)

        if request.attempt_id in self.world.applied_config_attempts:
            return RemediationResult(
                ok=True,
                summary=f"config {key}: already applied for attempt (no double-apply)",
                adapter_result={
                    "config_key": key,
                    "desired_value": desired,
                    "observed_value": self.world.configs.get(key),
                    "apply_count": self.world.config_apply_counts.get(key, 0),
                    "idempotent": True,
                },
                reconciliation_state=RECONCILE_APPLIED,
                skipped_execute=True,
            )

        self.world.configs[key] = desired
        self.world.config_apply_counts[key] = (
            self.world.config_apply_counts.get(key, 0) + 1
        )
        self.world.applied_config_attempts.add(request.attempt_id)

        if key in self.world.lose_ack_once:
            self.world.lose_ack_once.discard(key)
            raise LostAckError(
                f"lost ACK after config restore of {key} → {desired!r} "
                f"(mutate already landed; reconcile must observe APPLIED)"
            )

        return RemediationResult(
            ok=True,
            summary=f"restored config {key} → {desired!r}",
            adapter_result={
                "config_key": key,
                "desired_value": desired,
                "observed_value": desired,
                "apply_count": self.world.config_apply_counts[key],
            },
            reconciliation_state=RECONCILE_APPLIED,
        )
