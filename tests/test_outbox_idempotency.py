"""B6: outbox + idempotency helpers."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

psycopg = pytest.importorskip("psycopg")

from incidentpilot_shared import (  # noqa: E402
    OutboxRequiredError,
    UnitOfWork,
    try_begin_idempotent,
)


def _dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "incidentpilot")
    password = os.environ.get("IP_APP_PASSWORD", "incidentpilot_app")
    return f"postgresql://ip_app:{password}@{host}:{port}/{db}"


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.outbox_message LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="outbox tables not reachable (make compose-core && make migrate)",
)


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def test_atomic_domain_and_outbox_commit(conn: object) -> None:
    incident_id = uuid.uuid4()
    uow = UnitOfWork(conn, requires_outbox=True)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DETECTED', 'outbox atomic', 1)
            """,
            (str(incident_id), f"INC-OB-{uuid.uuid4().hex[:8]}"),
        )
    uow.enqueue_outbox(
        aggregate_type="incident",
        aggregate_id=str(incident_id),
        event_type="incident.created",
        payload={"state": "DETECTED"},
    )
    uow.commit()

    with psycopg.connect(_dsn()) as check:
        with check.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM domain.incident WHERE id = %s",
                (str(incident_id),),
            )
            assert cur.fetchone()[0] == 1
            cur.execute(
                """
                SELECT count(*) FROM domain.outbox_message
                WHERE aggregate_id = %s AND event_type = 'incident.created'
                """,
                (str(incident_id),),
            )
            assert cur.fetchone()[0] == 1


def test_atomic_domain_and_outbox_rollback(conn: object) -> None:
    incident_id = uuid.uuid4()
    uow = UnitOfWork(conn, requires_outbox=True)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DETECTED', 'outbox rollback', 1)
            """,
            (str(incident_id), f"INC-OB-{uuid.uuid4().hex[:8]}"),
        )
    uow.enqueue_outbox(
        aggregate_type="incident",
        aggregate_id=str(incident_id),
        event_type="incident.created",
        payload={"state": "DETECTED"},
    )
    uow.rollback()

    with psycopg.connect(_dsn()) as check:
        with check.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM domain.incident WHERE id = %s",
                (str(incident_id),),
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                "SELECT count(*) FROM domain.outbox_message WHERE aggregate_id = %s",
                (str(incident_id),),
            )
            assert cur.fetchone()[0] == 0


def test_marked_operation_requires_outbox(conn: object) -> None:
    uow = UnitOfWork(conn, requires_outbox=True)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DETECTED', 'missing outbox', 1)
            """,
            (str(uuid.uuid4()), f"INC-OB-{uuid.uuid4().hex[:8]}"),
        )
    with pytest.raises(OutboxRequiredError):
        uow.commit()


def test_duplicate_idempotency_key_is_noop(conn: object) -> None:
    scope = "test:webhook"
    key = f"fp-{uuid.uuid4().hex}"
    assert try_begin_idempotent(conn, scope=scope, key=key) is True
    assert try_begin_idempotent(conn, scope=scope, key=key) is False
    conn.commit()
    # After commit, still no-op
    with psycopg.connect(_dsn()) as check:
        assert try_begin_idempotent(check, scope=scope, key=key) is False
        check.commit()
