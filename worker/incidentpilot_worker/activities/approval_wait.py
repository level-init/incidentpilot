"""I5: approval timeout activity — expire + replan; never execute remediation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from incidentpilot_shared.domain.transitions import (
    IllegalTransitionError,
    IncidentState,
    StaleRevisionError,
)
from incidentpilot_worker.activities.incident_transitions import (
    ILLEGAL_TRANSITION_ERROR_TYPE,
    _raise_stale,
)
from incidentpilot_worker.commands import (
    expire_pending_approvals_command,
    transition_incident_command,
)
from incidentpilot_worker.db import connect


@activity.defn(name="handle_approval_timeout")
def handle_approval_timeout(incident_id: str) -> dict[str, Any]:
    """Expire PENDING approvals and replan (DIAGNOSED). Never executes adapters."""
    iid = UUID(incident_id)
    with connect() as conn:
        expired = expire_pending_approvals_command(
            conn,
            incident_id=iid,
            reason="approval_timeout",
            commit=False,
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT state, incident_revision
                FROM domain.incident
                WHERE id = %s
                """,
                (incident_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise LookupError(f"incident not found: {incident_id}")
            current = IncidentState(row[0])
            revision = int(row[1])

        to_state = current
        new_revision = revision
        skipped_transition = True
        if current is IncidentState.AWAITING_APPROVAL:
            try:
                result = transition_incident_command(
                    conn,
                    incident_id=iid,
                    expected_revision=revision,
                    to_state=IncidentState.DIAGNOSED,
                    actor="incident-workflow",
                    commit=False,
                )
                to_state = result.to_state
                new_revision = result.new_revision
                skipped_transition = False
            except StaleRevisionError as exc:
                _raise_stale(exc)
            except IllegalTransitionError as exc:
                raise ApplicationError(
                    str(exc),
                    type=ILLEGAL_TRANSITION_ERROR_TYPE,
                    non_retryable=True,
                ) from exc

        conn.commit()

    return {
        "incident_id": incident_id,
        "expired_count": expired.expired_count,
        "action_ids": [str(x) for x in expired.action_ids],
        "from_state": current.value,
        "to_state": to_state.value if hasattr(to_state, "value") else str(to_state),
        "revision": new_revision,
        "skipped_transition": skipped_transition,
        # Hard guarantee for I5 AC — timeout path never remediates.
        "remediation_executed": False,
    }
