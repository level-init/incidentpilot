"""B2 domain schema: hypothesis statuses, change types, published runbook immutability."""

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
                cur.execute("SELECT 1 FROM domain.hypothesis LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="B2 domain schema DB not reachable (make compose-core && make migrate)",
)


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(
        _dsn("ip_app", os.environ.get("IP_APP_PASSWORD", "incidentpilot_app")),
        autocommit=False,
    ) as connection:
        yield connection
        connection.rollback()


def _insert_incident(cur: object) -> str:
    incident_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
        VALUES (%s, %s, 'INVESTIGATING', 'hypo test', 1)
        """,
        (incident_id, f"INC-B2-{uuid.uuid4().hex[:8]}"),
    )
    return incident_id


def test_hypothesis_status_enum(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        for status in ("PROPOSED", "CONFIRMED", "REJECTED", "SUPERSEDED"):
            cur.execute(
                """
                INSERT INTO domain.hypothesis (
                    incident_id, status, statement, proposed_by, provenance
                ) VALUES (%s, %s, %s, 'system', '{}'::jsonb)
                """,
                (incident_id, status, f"stmt-{status}"),
            )
        cur.execute(
            """
            INSERT INTO domain.hypothesis (
                incident_id, status, statement, proposed_by
            ) VALUES (%s, 'LEADING', 'leading one', 'system')
            """,
            (incident_id,),
        )
        with pytest.raises(psycopg.Error):
            cur.execute(
                """
                INSERT INTO domain.hypothesis (
                    incident_id, status, statement, proposed_by
                ) VALUES (%s, 'LEADING', 'leading two', 'system')
                """,
                (incident_id,),
            )
        with pytest.raises(psycopg.Error):
            cur.execute(
                """
                INSERT INTO domain.hypothesis (
                    incident_id, status, statement, proposed_by
                ) VALUES (%s, 'NOT_A_STATUS', 'bad', 'system')
                """,
                (incident_id,),
            )


def test_change_type_constraint(conn: object) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.change (
                change_key, change_type, summary, source, fingerprint, observed_at
            ) VALUES (%s, 'DEPLOYMENT', 'deploy', 'github', %s, now())
            """,
            (f"CHG-{uuid.uuid4().hex[:10]}", f"cfp-{uuid.uuid4().hex}"),
        )
        with pytest.raises(psycopg.Error):
            cur.execute(
                """
                INSERT INTO domain.change (
                    change_key, change_type, summary, source, fingerprint, observed_at
                ) VALUES (%s, 'NOT_A_TYPE', 'x', 'github', %s, now())
                """,
                (f"CHG-{uuid.uuid4().hex[:10]}", f"cfp-{uuid.uuid4().hex}"),
            )


def _seed_published_runbook_version(cur: object) -> str:
    runbook_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO domain.runbook (id, key, title)
        VALUES (%s, %s, 'Rollback checkout')
        """,
        (runbook_id, f"rb-{uuid.uuid4().hex[:8]}"),
    )
    cur.execute(
        """
        INSERT INTO domain.runbook_version (
            id, runbook_id, version, status, body_markdown,
            allowed_action_types, proposed_by
        ) VALUES (
            %s, %s, 1, 'draft', '# rollback',
            ARRAY['ROLLBACK_DEPLOYMENT']::text[], 'system'
        )
        """,
        (version_id, runbook_id),
    )
    cur.execute(
        "UPDATE domain.runbook_version SET status = 'published' WHERE id = %s",
        (version_id,),
    )
    return version_id


def test_published_runbook_version_forbids_update(conn: object) -> None:
    with conn.cursor() as cur:
        version_id = _seed_published_runbook_version(cur)
        cur.execute(
            "SELECT published_at IS NOT NULL FROM domain.runbook_version WHERE id = %s",
            (version_id,),
        )
        assert cur.fetchone()[0] is True
        with pytest.raises(psycopg.Error, match="immutable once published"):
            cur.execute(
                """
                UPDATE domain.runbook_version
                SET body_markdown = '# mutated'
                WHERE id = %s
                """,
                (version_id,),
            )


def test_published_runbook_version_forbids_delete(conn: object) -> None:
    with conn.cursor() as cur:
        version_id = _seed_published_runbook_version(cur)
        with pytest.raises(psycopg.Error, match="immutable once published"):
            cur.execute("DELETE FROM domain.runbook_version WHERE id = %s", (version_id,))


def test_draft_runbook_version_can_edit(conn: object) -> None:
    with conn.cursor() as cur:
        runbook_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO domain.runbook (id, key, title) VALUES (%s, %s, 'draft rb')",
            (runbook_id, f"rb-{uuid.uuid4().hex[:8]}"),
        )
        cur.execute(
            """
            INSERT INTO domain.runbook_version (
                id, runbook_id, version, status, body_markdown, allowed_action_types
            ) VALUES (%s, %s, 1, 'draft', '# v1', ARRAY[]::text[])
            """,
            (version_id, runbook_id),
        )
        cur.execute(
            """
            UPDATE domain.runbook_version
            SET body_markdown = '# v1 edited',
                allowed_action_types = ARRAY['RESTART_WORKLOAD']::text[]
            WHERE id = %s
            """,
            (version_id,),
        )
        cur.execute(
            "SELECT body_markdown FROM domain.runbook_version WHERE id = %s",
            (version_id,),
        )
        assert cur.fetchone()[0] == "# v1 edited"
