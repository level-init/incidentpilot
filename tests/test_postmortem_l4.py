"""L4: Postmortem draft after RESOLVED + citation validator rejects uncited claims."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import (
    PostmortemNotReadyError,
    append_evidence_command,
    create_postmortem_draft_command,
)
from incidentpilot_shared.postmortem import (
    PostmortemCitation,
    PostmortemClaim,
    UnsupportedClaimError,
    parse_claim_dict,
    validate_postmortem_claims,
)
from incidentpilot_shared.timeline import append_timeline_event

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


def test_uncited_claim_rejected_unit() -> None:
    with pytest.raises(UnsupportedClaimError, match="uncited claim"):
        parse_claim_dict({"text": "root cause was a bad deploy", "citations": []})


def test_parse_requires_kind_prefix_for_string_tokens() -> None:
    with pytest.raises(UnsupportedClaimError, match="kind prefix"):
        parse_claim_dict(
            {
                "text": "something",
                "citations": ["not-a-prefixed-token"],
            }
        )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_draft_requires_resolved(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'MITIGATING', 'l4 not ready', 2)
            """,
            (str(incident_id), f"INC-L4-{uuid.uuid4().hex[:8]}"),
        )
    with pytest.raises(PostmortemNotReadyError, match="RESOLVED"):
        create_postmortem_draft_command(conn, incident_id=incident_id, commit=False)


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_unsupported_evidence_citation_rejected(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'RESOLVED', 'l4 bad cite', 5)
            """,
            (str(incident_id), f"INC-L4-{uuid.uuid4().hex[:8]}"),
        )
    claim = PostmortemClaim(
        text="invented observation",
        citations=(PostmortemCitation(kind="evidence", ref="EV-does-not-exist"),),
    )
    with pytest.raises(UnsupportedClaimError, match="unsupported claim citation"):
        validate_postmortem_claims(conn, incident_id=incident_id, claims=[claim])


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_draft_after_resolved_with_grounded_claims(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'RESOLVED', 'l4 checkout outage', 6)
            """,
            (str(incident_id), f"INC-L4-{uuid.uuid4().hex[:8]}"),
        )
    ev = append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="METRIC",
        fingerprint=f"l4-err-{uuid.uuid4().hex[:8]}",
        summary="checkout error rate elevated",
        producer="test_producer",
        payload={"value": 0.2},
        commit=False,
    )
    append_timeline_event(
        conn,
        incident_id=incident_id,
        event_type="STATE_TRANSITION",
        summary="RECOVERED → RESOLVED",
        actor="system",
        payload={"from": "RECOVERED", "to": "RESOLVED"},
    )
    action_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.action (
                id, incident_id, action_type, current_version, status, proposed_by
            ) VALUES (%s, %s, 'ROLLBACK_DEPLOYMENT', 1, 'SUCCEEDED', 'system')
            """,
            (str(action_id), str(incident_id)),
        )
        cur.execute(
            """
            INSERT INTO domain.action_version (
                action_id, version, action_type, proposed_by
            ) VALUES (%s, 1, 'ROLLBACK_DEPLOYMENT', 'system')
            """,
            (str(action_id),),
        )
        attempt_id = uuid.uuid4()
        cur.execute(
            """
            INSERT INTO domain.execution_attempt (
                id, action_id, action_version, attempt_number, state
            ) VALUES (%s, %s, 1, 1, 'SUCCEEDED')
            """,
            (str(attempt_id), str(action_id)),
        )
        validation_id = uuid.uuid4()
        cur.execute(
            """
            INSERT INTO domain.validation_result (
                id, incident_id, execution_attempt_id, outcome
            ) VALUES (%s, %s, %s, 'RECOVERED')
            """,
            (str(validation_id), str(incident_id), str(attempt_id)),
        )

    with pytest.raises(UnsupportedClaimError, match="uncited claim"):
        create_postmortem_draft_command(
            conn,
            incident_id=incident_id,
            claims=[{"text": "we are sure it was DNS", "citations": []}],
            commit=False,
        )

    draft = create_postmortem_draft_command(conn, incident_id=incident_id, commit=False)
    assert draft.status == "DRAFT"
    assert draft.inserted is True
    assert draft.claim_count >= 3
    assert ev.evidence_id in draft.cited_evidence_ids

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, body_markdown, cardinality(cited_evidence_ids),
                   provenance->'claims'
            FROM domain.postmortem
            WHERE id = %s
            """,
            (str(draft.postmortem_id),),
        )
        status, body, cite_n, claims = cur.fetchone()
    assert status == "DRAFT"
    assert "Grounded claims" in body
    assert cite_n >= 1
    assert isinstance(claims, list) and len(claims) == draft.claim_count
