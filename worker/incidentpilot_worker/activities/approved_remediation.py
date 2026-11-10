"""J10: APPROVED → reserve attempt → MITIGATING → verify/execute (sim rollback).

BLOCK never constructs/calls the adapter. ``execution_attempt`` is reserved
before the MITIGATING transition.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from incidentpilot_adapters.remediation import (
    SimDeploymentWorld,
    SimRollbackAdapter,
)
from incidentpilot_remediation.execute import verify_reconcile_and_execute
from incidentpilot_shared.domain.transitions import (
    IllegalTransitionError,
    IncidentState,
    StaleRevisionError,
)
from incidentpilot_shared.processors.policy import DECISION_BLOCK, assert_not_blocked
from incidentpilot_worker.activities.incident_transitions import (
    ILLEGAL_TRANSITION_ERROR_TYPE,
    _raise_stale,
)
from incidentpilot_worker.commands import (
    reserve_execution_attempt_command,
    transition_incident_command,
)
from incidentpilot_worker.db import connect

# Test seam: inject a shared SimDeploymentWorld for e2e apply_count asserts.
_SIM_WORLD: SimDeploymentWorld | None = None


def set_sim_deployment_world(world: SimDeploymentWorld | None) -> None:
    """Bind (or clear) the sim world used by APPROVED execute (tests)."""
    global _SIM_WORLD
    _SIM_WORLD = world


def get_sim_deployment_world() -> SimDeploymentWorld:
    global _SIM_WORLD
    if _SIM_WORLD is None:
        _SIM_WORLD = SimDeploymentWorld()
    return _SIM_WORLD


@activity.defn(name="handle_approval_approved")
def handle_approval_approved(payload: dict[str, Any]) -> dict[str, Any]:
    """Policy-gated remediation after Level-2 harness APPROVED (J10)."""
    incident_id = str(payload["incident_id"])
    action_id = UUID(str(payload["action_id"]))
    action_version = int(payload["action_version"])
    iid = UUID(incident_id)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT decision FROM domain.policy_decision
                WHERE action_id = %s AND action_version = %s
                """,
                (str(action_id), action_version),
            )
            pd = cur.fetchone()
            decision = str(pd[0]) if pd is not None else None

            cur.execute(
                """
                SELECT av.parameters, av.action_type
                FROM domain.action_version av
                WHERE av.action_id = %s AND av.version = %s
                """,
                (str(action_id), action_version),
            )
            ver = cur.fetchone()
            if ver is None:
                raise ApplicationError(
                    f"action_version {action_id} v{action_version} not found",
                    type="ActionVersionMissing",
                    non_retryable=True,
                )
            parameters = ver[0] if isinstance(ver[0], dict) else json.loads(ver[0] or "{}")
            action_type = str(ver[1])

            cur.execute(
                """
                SELECT state, incident_revision FROM domain.incident
                WHERE id = %s
                """,
                (incident_id,),
            )
            inc = cur.fetchone()
            if inc is None:
                raise LookupError(f"incident {incident_id} not found")
            current = str(inc[0])
            revision = int(inc[1])

        if decision == DECISION_BLOCK or decision is None:
            # Never construct/call adapter on BLOCK / missing policy.
            return {
                "incident_id": incident_id,
                "action_id": str(action_id),
                "action_version": action_version,
                "remediation_executed": False,
                "blocked": True,
                "policy_decision": decision,
                "adapter_execute_calls": 0,
            }

        try:
            assert_not_blocked(decision)
        except PermissionError as exc:
            return {
                "incident_id": incident_id,
                "action_id": str(action_id),
                "action_version": action_version,
                "remediation_executed": False,
                "blocked": True,
                "policy_decision": decision,
                "adapter_execute_calls": 0,
                "error": str(exc),
            }

        # 1) Reserve attempt BEFORE MITIGATING.
        attempt = reserve_execution_attempt_command(
            conn,
            action_id=action_id,
            action_version=action_version,
            commit=False,
        )

        # 2) AWAITING_APPROVAL → MITIGATING (or already MITIGATING).
        if current == IncidentState.AWAITING_APPROVAL.value:
            try:
                transitioned = transition_incident_command(
                    conn,
                    incident_id=iid,
                    expected_revision=revision,
                    to_state=IncidentState.MITIGATING,
                    actor="incident-workflow",
                    commit=False,
                )
                revision = transitioned.new_revision
                current = IncidentState.MITIGATING.value
            except StaleRevisionError as exc:
                _raise_stale(exc)
            except IllegalTransitionError as exc:
                raise ApplicationError(
                    str(exc),
                    type=ILLEGAL_TRANSITION_ERROR_TYPE,
                    non_retryable=True,
                ) from exc

        # 3) Verify + reconcile + execute (sim). J10 vertical: ROLLBACK_DEPLOYMENT.
        if action_type != "ROLLBACK_DEPLOYMENT":
            conn.commit()
            return {
                "incident_id": incident_id,
                "action_id": str(action_id),
                "action_version": action_version,
                "attempt_id": str(attempt.attempt_id),
                "remediation_executed": False,
                "blocked": False,
                "policy_decision": decision,
                "incident_state": current,
                "adapter_execute_calls": 0,
                "error": f"J10 sim execute supports ROLLBACK_DEPLOYMENT only (got {action_type})",
            }

        world = get_sim_deployment_world()
        adapter = SimRollbackAdapter(world)
        _verified, result = verify_reconcile_and_execute(
            conn,
            adapter,
            attempt_id=attempt.attempt_id,
            parameters=dict(parameters) if parameters else None,
            action_id=action_id,
            action_version=action_version,
            action_type=action_type,
        )
        conn.commit()

        deployment = str((parameters or {}).get("deployment") or "checkout")
        apply_count = int(world.apply_counts.get(deployment, 0))

    return {
        "incident_id": incident_id,
        "action_id": str(action_id),
        "action_version": action_version,
        "attempt_id": str(attempt.attempt_id),
        "remediation_executed": True,
        "blocked": False,
        "policy_decision": decision,
        "incident_state": current,
        "incident_revision": revision,
        "reconciliation_state": result.reconciliation_state,
        "adapter_execute_calls": len(adapter.execute_calls),
        "apply_count": apply_count,
        "skipped_execute": result.skipped_execute,
    }
