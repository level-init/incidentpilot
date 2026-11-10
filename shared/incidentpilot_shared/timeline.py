"""TimelineEvent helpers (L1) — process chronicle, not Evidence / not facts.

Timeline answers *what IncidentPilot did*. Evidence answers *what we observed
about the production system*. Do not treat timeline rows as production facts.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

if TYPE_CHECKING:
    from psycopg import Connection

# Canonical event_type values for emission hooks + docs/tests.
TIMELINE_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "INCIDENT_CREATED",
        "STATE_TRANSITION",
        "HYPOTHESIS_LEADING",
        "HYPOTHESIS_CONFIRMED",
        "RUNBOOK_PINNED",
        "SEVERITY_UPDATE",
        "ACTION_PROPOSED",
        "COMPENSATION_PROPOSED",
        "POLICY_DECISION",
        "APPROVAL_CREATED",
        "APPROVAL_DECIDED",
        "APPROVAL_TIMEOUT",
        "EXECUTION_ATTEMPT_RESERVED",
        "REMEDIATION_RESULT",
        "VALIDATION_RECORDED",
        "VALIDATION_ROUTED",
    }
)

# Expected readable order along a Level-2 bad-deploy path (subset).
BAD_DEPLOY_CHRONOLOGY: Final[tuple[str, ...]] = (
    "INCIDENT_CREATED",
    "STATE_TRANSITION",
    "ACTION_PROPOSED",
    "POLICY_DECISION",
    "APPROVAL_CREATED",
    "APPROVAL_DECIDED",
    "EXECUTION_ATTEMPT_RESERVED",
    "REMEDIATION_RESULT",
    "VALIDATION_RECORDED",
    "VALIDATION_ROUTED",
)


def append_timeline_event(
    conn: Connection,
    *,
    incident_id: UUID,
    event_type: str,
    summary: str,
    actor: str = "system",
    payload: dict[str, Any] | None = None,
) -> None:
    """Insert one append-only timeline row (caller owns TX)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                incident_id, event_type, summary, actor, payload
            ) VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                str(incident_id),
                event_type,
                summary,
                actor,
                json.dumps(payload or {}),
            ),
        )


def list_timeline_event_types(
    conn: Connection, *, incident_id: UUID
) -> list[str]:
    """Return event_type values in chronological order (oldest first)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_type
            FROM domain.timeline_event
            WHERE incident_id = %s
            ORDER BY occurred_at ASC, created_at ASC
            """,
            (str(incident_id),),
        )
        return [str(row[0]) for row in cur.fetchall()]
