"""Activities that re-read Postgres then call TransitionIncident (D2)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from temporalio import activity

from incidentpilot_shared.domain.transitions import IncidentState
from incidentpilot_worker.commands import transition_incident_command
from incidentpilot_worker.db import connect

# Early closed-loop path for IncidentWorkflow (D2).
_EARLY_PATH: tuple[IncidentState, ...] = (
    IncidentState.DETECTED,
    IncidentState.TRIAGING,
    IncidentState.INVESTIGATING,
)


def _rank(state: IncidentState) -> int:
    try:
        return _EARLY_PATH.index(state)
    except ValueError:
        return -1


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
def advance_incident_state(incident_id: str, to_state: str) -> dict[str, Any]:
    """Idempotent transition: re-read revision, then TransitionIncident command.

    Safe under activity retry / worker crash: if Postgres is already at or past
    ``to_state`` on the D2 path, this is a no-op (no duplicate Incident rows).
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

        result = transition_incident_command(
            conn,
            incident_id=UUID(incident_id),
            expected_revision=revision,
            to_state=target,
            actor="incident-workflow",
            commit=True,
        )
        return {
            "incident_id": incident_id,
            "from_state": result.from_state.value,
            "to_state": result.to_state.value,
            "revision": result.new_revision,
            "skipped": False,
        }


# Typing alias for callers/tests
IncidentSnapshot = dict[str, Any]
