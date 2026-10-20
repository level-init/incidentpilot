"""Transactional outbox + idempotency helpers (B6).

Semantics (at-least-once):
- Outbox rows are written in the **same DB transaction** as the domain change.
- A dispatcher (later epic) publishes pending rows and marks them published.
- Consumers must treat delivery as **at-least-once** and dedupe via
  `idempotency_record` (or event id) — duplicates are success/no-op.

Marked operations use `UnitOfWork(requires_outbox=True)` so a domain commit
cannot succeed without at least one outbox enqueue in that unit of work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from psycopg import Connection


class OutboxRequiredError(Exception):
    """Raised when a marked operation commits without enqueueing outbox messages."""


@dataclass
class UnitOfWork:
    """Thin TX helper that can require outbox writes before commit."""

    conn: Connection
    requires_outbox: bool = False
    _outbox_enqueued: int = field(default=0, init=False)

    def enqueue_outbox(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
        headers: dict[str, Any] | None = None,
        available_at: Any | None = None,
    ) -> UUID:
        message_id = enqueue_outbox(
            self.conn,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
            headers=headers,
            available_at=available_at,
        )
        self._outbox_enqueued += 1
        return message_id

    def try_begin_idempotent(
        self,
        *,
        scope: str,
        key: str,
        request_hash: str | None = None,
        response_ref: dict[str, Any] | None = None,
    ) -> bool:
        return try_begin_idempotent(
            self.conn,
            scope=scope,
            key=key,
            request_hash=request_hash,
            response_ref=response_ref,
        )

    def commit(self) -> None:
        if self.requires_outbox and self._outbox_enqueued < 1:
            raise OutboxRequiredError(
                "marked operation requires at least one outbox_message in the same TX"
            )
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()
        self._outbox_enqueued = 0


def enqueue_outbox(
    conn: Connection,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
    headers: dict[str, Any] | None = None,
    available_at: Any | None = None,
) -> UUID:
    """Insert a pending outbox row (caller owns the surrounding transaction)."""
    import json

    message_id = uuid4()
    with conn.cursor() as cur:
        if available_at is None:
            cur.execute(
                """
                INSERT INTO domain.outbox_message (
                    id, aggregate_type, aggregate_id, event_type, payload, headers
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (
                    str(message_id),
                    aggregate_type,
                    aggregate_id,
                    event_type,
                    json.dumps(payload),
                    json.dumps(headers or {}),
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO domain.outbox_message (
                    id, aggregate_type, aggregate_id, event_type,
                    payload, headers, available_at
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    str(message_id),
                    aggregate_type,
                    aggregate_id,
                    event_type,
                    json.dumps(payload),
                    json.dumps(headers or {}),
                    available_at,
                ),
            )
    return message_id


def try_begin_idempotent(
    conn: Connection,
    *,
    scope: str,
    key: str,
    request_hash: str | None = None,
    response_ref: dict[str, Any] | None = None,
) -> bool:
    """Record an idempotency key.

    Returns True if this is the first time the key is seen (caller should proceed).
    Returns False if the key already exists (duplicate → success/no-op).
    """
    import json

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.idempotency_record (
                scope, key, request_hash, response_ref
            ) VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (scope, key) DO NOTHING
            RETURNING key
            """,
            (
                scope,
                key,
                request_hash,
                json.dumps(response_ref or {}),
            ),
        )
        row = cur.fetchone()
        return row is not None
