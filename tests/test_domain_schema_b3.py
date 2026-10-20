"""B3 domain schema: action versions, approvals, policy, execution_attempt."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

psycopg = pytest.importorskip("psycopg")


def _dsn(user: str, password: str) -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "incidentpilot")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _db_available() -> bool:
    try:
        with psycopg.connect(
            _dsn("ip_app", os.environ.get("IP_APP_PASSWORD", "incidentpilot_app")),
            connect_timeout=2,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM domain.execution_attempt LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="B3 domain schema DB not reachable (make compose-core && make migrate)",
)


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(
        _dsn("ip_app", os.environ.get("IP_APP_PASSWORD", "incidentpilot_app")),
        autocommit=False,
    ) as connection:
        yield connection
        connection.rollback()


def _insert_incident(cur: object, state: str = "DIAGNOSED") -> str:
    incident_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
        VALUES (%s, %s, %s, 'b3 test', 1)
        """,
        (incident_id, f"INC-B3-{uuid.uuid4().hex[:8]}", state),
    )
    return incident_id


def _insert_action_with_version(cur: object, incident_id: str, version: int = 1) -> tuple[str, int]:
    action_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO domain.action (
            id, incident_id, action_type, current_version,
            is_reversible, reverse_action_type, proposed_by
        ) VALUES (
            %s, %s, 'ROLLBACK_DEPLOYMENT', %s,
            true, 'OTHER', 'system'
        )
        """,
        (action_id, incident_id, version),
    )
    cur.execute(
        """
        INSERT INTO domain.action_version (
            action_id, version, action_type, parameters, target_ref,
            is_reversible, reverse_action_type, proposed_by
        ) VALUES (
            %s, %s, 'ROLLBACK_DEPLOYMENT', '{"rev":"abc"}'::jsonb, '{}'::jsonb,
            true, 'OTHER', 'system'
        )
        """,
        (action_id, version),
    )
    return action_id, version


def test_approval_requires_existing_action_version(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        action_id, version = _insert_action_with_version(cur, incident_id)
        cur.execute(
            """
            INSERT INTO domain.approval (action_id, action_version, status)
            VALUES (%s, %s, 'PENDING')
            """,
            (action_id, version),
        )
        with pytest.raises(psycopg.Error):
            cur.execute(
                """
                INSERT INTO domain.approval (action_id, action_version, status)
                VALUES (%s, %s, 'PENDING')
                """,
                (action_id, 99),
            )


def test_policy_unique_per_action_version(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        action_id, version = _insert_action_with_version(cur, incident_id)
        cur.execute(
            """
            INSERT INTO domain.policy_decision (
                action_id, action_version, decision, reason
            ) VALUES (%s, %s, 'REQUIRE_APPROVAL', 'level2')
            """,
            (action_id, version),
        )
        with pytest.raises(psycopg.Error):
            cur.execute(
                """
                INSERT INTO domain.policy_decision (
                    action_id, action_version, decision
                ) VALUES (%s, %s, 'BLOCK')
                """,
                (action_id, version),
            )


def test_approval_unique_per_action_version(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        action_id, version = _insert_action_with_version(cur, incident_id)
        cur.execute(
            """
            INSERT INTO domain.approval (action_id, action_version, status)
            VALUES (%s, %s, 'PENDING')
            """,
            (action_id, version),
        )
        with pytest.raises(psycopg.Error):
            cur.execute(
                """
                INSERT INTO domain.approval (action_id, action_version, status)
                VALUES (%s, %s, 'APPROVED')
                """,
                (action_id, version),
            )


def test_execution_attempt_before_mitigating(conn: object) -> None:
    """execution_attempt is persistable before incident reaches MITIGATING."""
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur, state="AWAITING_APPROVAL")
        action_id, version = _insert_action_with_version(cur, incident_id)
        cur.execute(
            """
            INSERT INTO domain.execution_attempt (
                action_id, action_version, attempt_number, state
            ) VALUES (%s, %s, 1, 'RESERVED')
            """,
            (action_id, version),
        )
        cur.execute(
            """
            SELECT state FROM domain.execution_attempt
            WHERE action_id = %s AND action_version = %s
            """,
            (action_id, version),
        )
        assert cur.fetchone()[0] == "RESERVED"
        cur.execute("SELECT state FROM domain.incident WHERE id = %s", (incident_id,))
        assert cur.fetchone()[0] == "AWAITING_APPROVAL"


def test_action_version_immutable(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        action_id, version = _insert_action_with_version(cur, incident_id)
        with pytest.raises(psycopg.Error, match="immutable"):
            cur.execute(
                """
                UPDATE domain.action_version
                SET parameters = '{"x":1}'::jsonb
                WHERE action_id = %s AND version = %s
                """,
                (action_id, version),
            )


def test_action_reversibility_fields(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        action_id, _version = _insert_action_with_version(cur, incident_id)
        cur.execute(
            """
            SELECT is_reversible, reverse_action_type
            FROM domain.action WHERE id = %s
            """,
            (action_id,),
        )
        row = cur.fetchone()
        assert row[0] is True
        assert row[1] == "OTHER"
