"""Activities that transition incidents with expected_revision (D2/D3).

StaleRevision is mapped to a non-retryable Temporal ApplicationError so a
lagging activity attempt cannot mutate after a newer revision landed. The
workflow re-queries Postgres and retries with a fresh revision.
"""

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
from incidentpilot_worker.commands import transition_incident_command
from incidentpilot_worker.db import connect

# Early closed-loop path for IncidentWorkflow (D2).
_EARLY_PATH: tuple[IncidentState, ...] = (
    IncidentState.DETECTED,
    IncidentState.TRIAGING,
    IncidentState.INVESTIGATING,
)

STALE_REVISION_ERROR_TYPE = "StaleRevision"
ILLEGAL_TRANSITION_ERROR_TYPE = "IllegalTransition"


def _rank(state: IncidentState) -> int:
    try:
        return _EARLY_PATH.index(state)
    except ValueError:
        return -1


def _raise_stale(exc: StaleRevisionError) -> None:
    raise ApplicationError(
        str(exc),
        type=STALE_REVISION_ERROR_TYPE,
        non_retryable=True,
    ) from exc


@activity.defn(name="load_incident_snapshot")
def load_incident_snapshot(incident_id: str) -> dict[str, Any]:
    """Re-read incident state + revision from Postgres (no mutation)."""
    with connect() as conn, conn.cursor() as cur:
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
        return {"incident_id": incident_id, "state": row[0], "revision": int(row[1])}


@activity.defn(name="advance_incident_state")
def advance_incident_state(
    incident_id: str,
    to_state: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Transition with caller-supplied expected_revision (fail closed on stale).

    Idempotent when Postgres is already at/past ``to_state`` on the D2 path.
    Otherwise requires ``expected_revision`` to match the row; mismatches raise
    non-retryable ``StaleRevision`` so Temporal will not keep hammering.
    """
    target = IncidentState(to_state)
    with connect() as conn:
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

        # Already applied (activity retry / concurrent success) — no mutate.
        if current is target or (
            _rank(current) >= 0 and _rank(target) >= 0 and _rank(current) >= _rank(target)
        ):
            return {
                "incident_id": incident_id,
                "from_state": current.value,
                "to_state": current.value,
                "revision": revision,
                "skipped": True,
            }

        if revision != expected_revision:
            _raise_stale(
                StaleRevisionError(
                    incident_id=UUID(incident_id),
                    expected_revision=expected_revision,
                    actual_revision=revision,
                )
            )

        try:
            result = transition_incident_command(
                conn,
                incident_id=UUID(incident_id),
                expected_revision=expected_revision,
                to_state=target,
                actor="incident-workflow",
                commit=True,
            )
        except StaleRevisionError as exc:
            _raise_stale(exc)
        except IllegalTransitionError as exc:
            raise ApplicationError(
                str(exc),
                type=ILLEGAL_TRANSITION_ERROR_TYPE,
                non_retryable=True,
            ) from exc

        return {
            "incident_id": incident_id,
            "from_state": result.from_state.value,
            "to_state": result.to_state.value,
            "revision": result.new_revision,
            "skipped": False,
        }


IncidentSnapshot = dict[str, Any]
