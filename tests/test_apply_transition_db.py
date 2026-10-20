"""B5 DB apply_transition (optional; requires migrated Postgres)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

psycopg = pytest.importorskip("psycopg")

from incidentpilot_shared.domain import (  # noqa: E402
    IncidentState,
    StaleRevisionError,
    apply_transition,
)


def _dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "incidentpilot")
    user = "ip_app"
    password = os.environ.get("IP_APP_PASSWORD", "incidentpilot_app")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _db_available() -> bool:
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.incident LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="Postgres not reachable for apply_transition",
)


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def test_apply_transition_bumps_revision(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DETECTED', 'transition db', 1)
            """,
            (str(incident_id), f"INC-T-{uuid.uuid4().hex[:8]}"),
        )
    result = apply_transition(
        conn,
        incident_id=incident_id,
        expected_revision=1,
        to_state=IncidentState.INVESTIGATING,
    )
    assert result.new_revision == 2
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state, incident_revision FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        state, rev = cur.fetchone()
        assert state == "INVESTIGATING"
        assert rev == 2


def test_apply_transition_stale_revision(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DETECTED', 'stale', 3)
            """,
            (str(incident_id), f"INC-T-{uuid.uuid4().hex[:8]}"),
        )
    with pytest.raises(StaleRevisionError):
        apply_transition(
            conn,
            incident_id=incident_id,
            expected_revision=1,
            to_state=IncidentState.TRIAGING,
        )
