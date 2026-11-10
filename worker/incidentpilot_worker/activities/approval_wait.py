"""I5/I6: approval timeout/reject activities — replan; never execute remediation."""

from __future__ import annotations

import json
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


def _replan_to_diagnosed(
    conn: object,
    *,
    incident_id: str,
    actor: str,
) -> tuple[IncidentState, IncidentState | str, int, bool]:
    """AWAITING_APPROVAL → DIAGNOSED (replan). Returns from, to, revision, skipped."""
    iid = UUID(incident_id)
    with conn.cursor() as cur:  # type: ignore[attr-defined]
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

    to_state: IncidentState | str = current
    new_revision = revision
    skipped_transition = True
    if current is IncidentState.AWAITING_APPROVAL:
        try:
            result = transition_incident_command(
                conn,  # type: ignore[arg-type]
                incident_id=iid,
                expected_revision=revision,
                to_state=IncidentState.DIAGNOSED,
                actor=actor,
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
    return current, to_state, new_revision, skipped_transition


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
        current, to_state, new_revision, skipped = _replan_to_diagnosed(
            conn,
            incident_id=incident_id,
            actor="incident-workflow",
        )
        conn.commit()

    return {
        "incident_id": incident_id,
        "expired_count": expired.expired_count,
        "action_ids": [str(x) for x in expired.action_ids],
        "from_state": current.value,
        "to_state": to_state.value if hasattr(to_state, "value") else str(to_state),
        "revision": new_revision,
        "skipped_transition": skipped,
        "remediation_executed": False,
        "reason": "approval_timeout",
    }


@activity.defn(name="handle_approval_rejected")
def handle_approval_rejected(incident_id: str) -> dict[str, Any]:
    """I6: reject already recorded in domain — replan without execute."""
    with connect() as conn:
        current, to_state, new_revision, skipped = _replan_to_diagnosed(
            conn,
            incident_id=incident_id,
            actor="incident-workflow",
        )
        if not skipped:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO domain.timeline_event (
                        incident_id, event_type, summary, actor, payload
                    ) VALUES (
                        %s, 'APPROVAL_REJECT_REPLAN', %s, 'system', %s::jsonb
                    )
                    """,
                    (
                        incident_id,
                        "approval rejected — replan to DIAGNOSED",
                        json.dumps(
                            {
                                "remediation_executed": False,
                                "reason": "approval_rejected",
                            }
                        ),
                    ),
                )
        conn.commit()

    return {
        "incident_id": incident_id,
        "from_state": current.value,
        "to_state": to_state.value if hasattr(to_state, "value") else str(to_state),
        "revision": new_revision,
        "skipped_transition": skipped,
        "remediation_executed": False,
        "reason": "approval_rejected",
    }
