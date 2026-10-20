"""B4 domain schema: impact, timeline/audit append-only, AIInvocation, postmortem."""

from __future__ import annotations

import json
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
                cur.execute("SELECT 1 FROM domain.timeline_event LIMIT 1")
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="B4 domain schema DB not reachable (make compose-core && make migrate)",
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
        VALUES (%s, %s, 'RESOLVED', 'b4 test', 1)
        """,
        (incident_id, f"INC-B4-{uuid.uuid4().hex[:8]}"),
    )
    return incident_id


def test_timeline_append_only(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        event_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO domain.timeline_event (
                id, incident_id, event_type, summary, actor
            ) VALUES (%s, %s, 'STATE_TRANSITION', 'to RESOLVED', 'system')
            """,
            (event_id, incident_id),
        )
        with pytest.raises(psycopg.Error, match="append-only"):
            cur.execute(
                "UPDATE domain.timeline_event SET summary = 'mutated' WHERE id = %s",
                (event_id,),
            )


def test_audit_append_only(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        event_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO domain.audit_event (
                id, incident_id, action, actor, resource_type, resource_id
            ) VALUES (%s, %s, 'approval.decide', 'admin', 'approval', 'a1')
            """,
            (event_id, incident_id),
        )
        with pytest.raises(psycopg.Error, match="append-only"):
            cur.execute("DELETE FROM domain.audit_event WHERE id = %s", (event_id,))


def test_postmortem_corrective_actions_and_final(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        actions = [{"title": "Add deploy canary", "owner": "platform"}]
        cur.execute(
            """
            INSERT INTO domain.postmortem (
                incident_id, status, title, body_markdown, corrective_actions
            ) VALUES (%s, 'DRAFT', 'PM', 'draft body', %s::jsonb)
            """,
            (incident_id, json.dumps(actions)),
        )
        cur.execute(
            "SELECT jsonb_typeof(corrective_actions), corrective_actions->0->>'title' "
            "FROM domain.postmortem WHERE incident_id = %s",
            (incident_id,),
        )
        kind, title = cur.fetchone()
        assert kind == "array"
        assert title == "Add deploy canary"

        cur.execute(
            "UPDATE domain.postmortem SET status = 'FINAL' WHERE incident_id = %s",
            (incident_id,),
        )
        cur.execute(
            "SELECT finalized_at IS NOT NULL FROM domain.postmortem WHERE incident_id = %s",
            (incident_id,),
        )
        assert cur.fetchone()[0] is True

        with pytest.raises(psycopg.Error, match="FINAL"):
            cur.execute(
                "UPDATE domain.postmortem SET title = 'nope' WHERE incident_id = %s",
                (incident_id,),
            )


def test_ai_invocation_minimum_fields(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        cur.execute(
            """
            INSERT INTO domain.ai_invocation (
                incident_id, purpose, provider, model,
                prompt_hash, response_hash, input_tokens, output_tokens, status
            ) VALUES (
                %s, 'hypothesis_rank', 'openai', 'gpt-test',
                'ph', 'rh', 10, 20, 'succeeded'
            )
            """,
            (incident_id,),
        )
        cur.execute(
            """
            SELECT purpose, provider, model FROM domain.ai_invocation
            WHERE incident_id = %s
            """,
            (incident_id,),
        )
        assert cur.fetchone() == ("hypothesis_rank", "openai", "gpt-test")


def test_impact_and_slo_burn_insert(conn: object) -> None:
    with conn.cursor() as cur:
        incident_id = _insert_incident(cur)
        cur.execute(
            """
            INSERT INTO domain.impact_snapshot (
                incident_id, severity, customer_impact_summary, estimated_affected_users
            ) VALUES (%s, 'SEV2', 'checkout errors', 1200)
            """,
            (incident_id,),
        )
        cur.execute(
            """
            INSERT INTO domain.slo_burn (
                incident_id, slo_key, window_label, burn_rate, error_budget_remaining
            ) VALUES (%s, 'checkout_availability', '1h', 14.5, 0.12)
            """,
            (incident_id,),
        )
        cur.execute(
            "SELECT count(*) FROM domain.impact_snapshot WHERE incident_id = %s",
            (incident_id,),
        )
        assert cur.fetchone()[0] == 1
