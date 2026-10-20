"""TransitionIncident — single authority for Incident state machine (B5 / Freeze-2)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from psycopg import Connection


class IncidentState(StrEnum):
    DETECTED = "DETECTED"
    TRIAGING = "TRIAGING"
    INVESTIGATING = "INVESTIGATING"
    DIAGNOSED = "DIAGNOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    MITIGATING = "MITIGATING"
    VALIDATING = "VALIDATING"
    RECOVERED = "RECOVERED"
    RESOLVED = "RESOLVED"
    DEGRADED = "DEGRADED"
    POSTMORTEM = "POSTMORTEM"
    CLOSED = "CLOSED"


# Legal edges only. Explicitly illegal examples called out in #10:
# - VALIDATING → MITIGATING
# - RESOLVED → CLOSED (must pass POSTMORTEM)
LEGAL_TRANSITIONS: dict[IncidentState, frozenset[IncidentState]] = {
    IncidentState.DETECTED: frozenset({IncidentState.TRIAGING, IncidentState.INVESTIGATING}),
    IncidentState.TRIAGING: frozenset({IncidentState.INVESTIGATING}),
    IncidentState.INVESTIGATING: frozenset({IncidentState.DIAGNOSED}),
    IncidentState.DIAGNOSED: frozenset(
        {
            IncidentState.AWAITING_APPROVAL,
            IncidentState.MITIGATING,
            IncidentState.DEGRADED,
        }
    ),
    IncidentState.AWAITING_APPROVAL: frozenset(
        {
            IncidentState.MITIGATING,
            IncidentState.DIAGNOSED,
            IncidentState.DEGRADED,
        }
    ),
    IncidentState.MITIGATING: frozenset({IncidentState.VALIDATING, IncidentState.DEGRADED}),
    IncidentState.VALIDATING: frozenset({IncidentState.RECOVERED, IncidentState.DEGRADED}),
    IncidentState.RECOVERED: frozenset({IncidentState.RESOLVED, IncidentState.DEGRADED}),
    IncidentState.RESOLVED: frozenset({IncidentState.POSTMORTEM}),
    IncidentState.DEGRADED: frozenset(
        {
            IncidentState.DIAGNOSED,
            IncidentState.INVESTIGATING,
            IncidentState.AWAITING_APPROVAL,
            IncidentState.MITIGATING,
        }
    ),
    IncidentState.POSTMORTEM: frozenset({IncidentState.CLOSED}),
    IncidentState.CLOSED: frozenset(),
}


class StaleRevisionError(Exception):
    """Raised when expected_revision does not match the current incident_revision."""

    def __init__(
        self,
        *,
        incident_id: UUID,
        expected_revision: int,
        actual_revision: int,
    ) -> None:
        self.incident_id = incident_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            f"stale revision for incident {incident_id}: "
            f"expected {expected_revision}, actual {actual_revision}"
        )


class IllegalTransitionError(Exception):
    """Raised when from_state → to_state is not a legal Freeze-2 edge."""

    def __init__(
        self,
        *,
        incident_id: UUID | None,
        from_state: IncidentState,
        to_state: IncidentState,
    ) -> None:
        self.incident_id = incident_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"illegal transition: {from_state} → {to_state}")


@dataclass(frozen=True, slots=True)
class TransitionResult:
    incident_id: UUID
    from_state: IncidentState
    to_state: IncidentState
    previous_revision: int
    new_revision: int


def transition_incident(
    *,
    incident_id: UUID,
    current_state: IncidentState | str,
    expected_revision: int,
    actual_revision: int,
    to_state: IncidentState | str,
) -> TransitionResult:
    """Pure TransitionIncident(expected_revision) decision.

    Callers persist the resulting state + new_revision (see apply_transition).
    """
    from_state = IncidentState(current_state)
    target = IncidentState(to_state)

    if expected_revision != actual_revision:
        raise StaleRevisionError(
            incident_id=incident_id,
            expected_revision=expected_revision,
            actual_revision=actual_revision,
        )

    allowed = LEGAL_TRANSITIONS[from_state]
    if target not in allowed:
        raise IllegalTransitionError(
            incident_id=incident_id,
            from_state=from_state,
            to_state=target,
        )

    return TransitionResult(
        incident_id=incident_id,
        from_state=from_state,
        to_state=target,
        previous_revision=actual_revision,
        new_revision=actual_revision + 1,
    )


def apply_transition(
    conn: Connection,
    *,
    incident_id: UUID,
    expected_revision: int,
    to_state: IncidentState | str,
) -> TransitionResult:
    """Load incident, apply TransitionIncident, persist state + revision bump."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT state, incident_revision
            FROM domain.incident
            WHERE id = %s
            FOR UPDATE
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"incident not found: {incident_id}")

        current_state, actual_revision = IncidentState(row[0]), int(row[1])
        result = transition_incident(
            incident_id=incident_id,
            current_state=current_state,
            expected_revision=expected_revision,
            actual_revision=actual_revision,
            to_state=to_state,
        )

        cur.execute(
            """
            UPDATE domain.incident
            SET state = %s,
                incident_revision = %s,
                updated_at = now(),
                resolved_at = CASE
                    WHEN %s = 'RESOLVED' AND resolved_at IS NULL THEN now()
                    ELSE resolved_at
                END,
                closed_at = CASE
                    WHEN %s = 'CLOSED' AND closed_at IS NULL THEN now()
                    ELSE closed_at
                END
            WHERE id = %s AND incident_revision = %s
            """,
            (
                result.to_state.value,
                result.new_revision,
                result.to_state.value,
                result.to_state.value,
                str(incident_id),
                result.previous_revision,
            ),
        )
        if cur.rowcount != 1:
            raise StaleRevisionError(
                incident_id=incident_id,
                expected_revision=expected_revision,
                actual_revision=actual_revision,
            )

    return result
