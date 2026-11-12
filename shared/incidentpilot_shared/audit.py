"""AuditEvent helpers (L2) — privileged who/what/when trail, not Timeline.

Audit answers *who authorized or changed what*. Timeline answers *what the
process did*. Keep them distinct; never treat audit rows as production facts.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

if TYPE_CHECKING:
    from psycopg import Connection

AuditOutcome = Literal["success", "denied", "error"]

# Canonical ``action`` values for writers + docs/tests.
AUDIT_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "incident.create",
        "incident.severity_update",
        "incident.manual_resolve",
        "policy.publish",
        "policy.activate",
        "policy.evaluate",
        "hypothesis.confirm",
        "approval.decide",
        "remediation.execute",
        "admin.autonomy_upsert",
    }
)


def append_audit_event(
    conn: Connection,
    *,
    action: str,
    actor: str,
    resource_type: str,
    resource_id: str | None = None,
    incident_id: UUID | None = None,
    outcome: AuditOutcome = "success",
    details: dict[str, Any] | None = None,
) -> None:
    """Insert one append-only audit row (caller owns TX)."""
    if outcome not in {"success", "denied", "error"}:
        raise ValueError(f"invalid audit outcome: {outcome!r}")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.audit_event (
                incident_id, action, actor, resource_type, resource_id,
                outcome, details
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                str(incident_id) if incident_id is not None else None,
                action,
                actor,
                resource_type,
                resource_id,
                outcome,
                json.dumps(details or {}),
            ),
        )


def list_audit_actions(
    conn: Connection,
    *,
    incident_id: UUID,
) -> list[str]:
    """Return audit ``action`` values in chronological order (oldest first)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT action
            FROM domain.audit_event
            WHERE incident_id = %s
            ORDER BY occurred_at ASC, created_at ASC
            """,
            (str(incident_id),),
        )
        return [str(row[0]) for row in cur.fetchall()]
