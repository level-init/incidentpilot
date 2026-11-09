"""H9: Historical retrieval assist — suggestions only, never Evidence."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.ai_tool_broker import AiToolBroker
from incidentpilot_shared.domain.commands import (
    MissingEvidenceCitationError,
    create_incident_command,
    propose_hypothesis_command,
    resolve_incident_evidence_refs,
)
from incidentpilot_shared.history import (
    HISTORICAL_SUGGESTION_PREFIX,
    retrieve_historical_assist,
    suggestion_id_for,
)
from incidentpilot_shared.tool_scope import ToolScope

psycopg = pytest.importorskip("psycopg")


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
                cur.execute("SELECT 1 FROM domain.postmortem LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def test_suggestion_id_prefix() -> None:
    sid = suggestion_id_for("INC-ABCDEF12")
    assert sid.startswith(HISTORICAL_SUGGESTION_PREFIX)
    assert "INC-ABCDEF12" in sid


def test_broker_historical_search_marks_non_authoritative() -> None:
    incident_id = str(uuid.uuid4())
    broker = AiToolBroker(scope=ToolScope(incident_id=incident_id, environment="local"))
    result = broker.invoke(
        "historical_search",
        {"incident_id": incident_id, "query": "checkout"},
    )
    assert result.ok
    assert result.data is not None
    assert result.data["authoritative"] is False
    assert result.data["may_cite_as_evidence"] is False
    assert "not Evidence" in result.data["disclaimer"]


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_retrieve_past_incident_and_reject_hist_citation(conn: object) -> None:
    past = create_incident_command(
        conn, title="checkout high error rate outage", severity="SEV2", commit=False
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE domain.incident
            SET state = 'RESOLVED', resolved_at = now(), updated_at = now()
            WHERE id = %s
            """,
            (str(past.incident_id),),
        )
        cur.execute(
            """
            INSERT INTO domain.postmortem (
                incident_id, status, title, body_markdown, corrective_actions
            ) VALUES (
                %s, 'FINAL', 'Checkout error-rate postmortem',
                'Bad deploy caused elevated checkout errors.', '[]'::jsonb
            )
            """,
            (str(past.incident_id),),
        )

    current = create_incident_command(
        conn, title="fresh checkout spike", severity="SEV3", commit=False
    )

    hits = retrieve_historical_assist(
        conn,
        query="checkout error",
        exclude_incident_id=current.incident_id,
    )
    assert hits
    hit = next(h for h in hits if h.incident_id == past.incident_id)
    assert hit.authoritative is False
    assert hit.may_cite_as_evidence is False
    assert hit.suggestion_id.startswith(HISTORICAL_SUGGESTION_PREFIX)
    assert hit.postmortem_title is not None

    with pytest.raises(MissingEvidenceCitationError, match="not Evidence"):
        resolve_incident_evidence_refs(
            conn,
            incident_id=current.incident_id,
            refs=[hit.suggestion_id],
        )

    with pytest.raises(MissingEvidenceCitationError, match="not Evidence"):
        propose_hypothesis_command(
            conn,
            incident_id=current.incident_id,
            statement="same as last time",
            cited_evidence_ids=[hit.suggestion_id],
            commit=False,
        )
