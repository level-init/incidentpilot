"""Persist verified Slack interactive payloads (K2) before HTTP ack.

K3 maps ``RECEIVED`` rows to ``ApprovalDecision``. This module does not decide
approvals — durable ingress only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from psycopg import Connection


@dataclass(frozen=True, slots=True)
class PersistSlackInteractionResult:
    interaction_id: UUID
    inserted: bool
    status: str
    slack_trigger_id: str | None
    interaction_type: str


def _fetch_by_trigger(
    conn: Connection, trigger_id: str
) -> PersistSlackInteractionResult | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, interaction_type
            FROM domain.slack_interaction
            WHERE slack_trigger_id = %s
            """,
            (trigger_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return PersistSlackInteractionResult(
        interaction_id=UUID(str(row[0])),
        inserted=False,
        status=str(row[1]),
        slack_trigger_id=trigger_id,
        interaction_type=str(row[2]),
    )


def persist_slack_interaction_command(
    conn: Connection,
    *,
    payload: dict[str, Any],
    request_timestamp: int,
    ingress_id: str,
    commit: bool = True,
) -> PersistSlackInteractionResult:
    """Insert a ``domain.slack_interaction`` row (idempotent on ``trigger_id``)."""
    from psycopg.errors import UniqueViolation

    interaction_type = str(payload.get("type") or "unknown")
    trigger_raw = payload.get("trigger_id")
    trigger_id = str(trigger_raw).strip() if trigger_raw else None
    if trigger_id == "":
        trigger_id = None

    if trigger_id is not None:
        existing = _fetch_by_trigger(conn, trigger_id)
        if existing is not None:
            if commit:
                conn.commit()
            return existing

    interaction_id = uuid4()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO domain.slack_interaction (
                    id, slack_trigger_id, interaction_type, payload,
                    request_timestamp, ingress_id, status
                ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, 'RECEIVED')
                RETURNING id, status
                """,
                (
                    str(interaction_id),
                    trigger_id,
                    interaction_type,
                    json.dumps(payload),
                    request_timestamp,
                    ingress_id,
                ),
            )
            row = cur.fetchone()
            assert row is not None
        if commit:
            conn.commit()
        return PersistSlackInteractionResult(
            interaction_id=UUID(str(row[0])),
            inserted=True,
            status=str(row[1]),
            slack_trigger_id=trigger_id,
            interaction_type=interaction_type,
        )
    except UniqueViolation:
        conn.rollback()
        if trigger_id is None:
            raise
        existing = _fetch_by_trigger(conn, trigger_id)
        if existing is None:
            raise
        if commit:
            conn.commit()
        return existing
