"""B1 domain schema: migrations, alert fingerprint, evidence immutability."""

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
                cur.execute("SELECT 1 FROM domain.incident LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="domain schema DB not reachable (make compose-core && make migrate)",
)


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(
        _dsn("ip_app", os.environ.get("IP_APP_PASSWORD", "incidentpilot_app")),
        autocommit=False,
    ) as connection:
        yield connection
        connection.rollback()


def _insert_service(cur: object, key: str) -> str:
    service_id = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO domain.service (id, key, display_name, environment)
        VALUES (%s, %s, %s, 'local')
        """,
        (service_id, key, key),
    )
    return service_id


def _insert_incident(cur: object) -> str:
    incident_id = str(uuid.uuid4())
    public_id = f"INC-TEST-{uuid.uuid4().hex[:8]}"
    cur.execute(
        """
        INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
        VALUES (%s, %s, 'DETECTED', 'test incident', 1)
        """,
        (incident_id, public_id),
    )
    return incident_id


def test_incident_revision_column_exists(conn: object) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'domain'
              AND table_name = 'incident'
              AND column_name = 'incident_revision'
            """
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "incident_revision"


def test_alert_fingerprint_unique(conn: object) -> None:
    fp = f"fp-{uuid.uuid4().hex}"
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        cur.execute(
            """
            INSERT INTO domain.alert (fingerprint, source, incident_id)
            VALUES (%s, 'alertmanager', %s)
            """,
            (fp, incident_id),
        )
        with pytest.raises(psycopg.Error):
            cur.execute(
                """
                INSERT INTO domain.alert (fingerprint, source, incident_id)
                VALUES (%s, 'alertmanager', %s)
                """,
                (fp, incident_id),
            )


def test_evidence_append_only_forbids_update(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        evidence_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO domain.evidence (
                id, evidence_key, incident_id, kind, fingerprint,
                summary, payload, provenance, observed_at, producer
            ) VALUES (
                %s, %s, %s, 'LOG', %s,
                'orig', '{}'::jsonb, '{}'::jsonb, now(), 'test'
            )
            """,
            (evidence_id, f"EV-{uuid.uuid4().hex[:12]}", incident_id, f"evfp-{uuid.uuid4().hex}"),
        )
        with pytest.raises(psycopg.Error, match="append-only"):
            cur.execute(
                "UPDATE domain.evidence SET summary = 'mutated' WHERE id = %s",
                (evidence_id,),
            )


def test_evidence_append_only_forbids_delete(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        evidence_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO domain.evidence (
                id, evidence_key, incident_id, kind, fingerprint,
                summary, payload, provenance, observed_at, producer
            ) VALUES (
                %s, %s, %s, 'METRIC', %s,
                'keep', '{}'::jsonb, '{}'::jsonb, now(), 'test'
            )
            """,
            (evidence_id, f"EV-{uuid.uuid4().hex[:12]}", incident_id, f"evfp-{uuid.uuid4().hex}"),
        )
        with pytest.raises(psycopg.Error, match="append-only"):
            cur.execute("DELETE FROM domain.evidence WHERE id = %s", (evidence_id,))


def test_incident_service_and_evidence_relation(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        service_id = _insert_service(cur, f"svc-{uuid.uuid4().hex[:8]}")
        cur.execute(
            """
            INSERT INTO domain.incident_service (incident_id, service_id, involvement)
            VALUES (%s, %s, 'affected')
            """,
            (incident_id, service_id),
        )
        e1 = str(uuid.uuid4())
        e2 = str(uuid.uuid4())
        for eid, kind in ((e1, "LOG"), (e2, "TRACE")):
            cur.execute(
                """
                INSERT INTO domain.evidence (
                    id, evidence_key, incident_id, kind, fingerprint,
                    summary, observed_at, producer, service_id
                ) VALUES (%s, %s, %s, %s, %s, 'rel', now(), 'test', %s)
                """,
                (
                    eid,
                    f"EV-{uuid.uuid4().hex[:12]}",
                    incident_id,
                    kind,
                    f"evfp-{uuid.uuid4().hex}",
                    service_id,
                ),
            )
        cur.execute(
            """
            INSERT INTO domain.evidence_relation (
                from_evidence_id, to_evidence_id, relation_type
            ) VALUES (%s, %s, 'SUPPORTS')
            """,
            (e1, e2),
        )
        cur.execute(
            "SELECT count(*) FROM domain.evidence_relation WHERE from_evidence_id = %s",
            (e1,),
        )
        assert cur.fetchone()[0] == 1
