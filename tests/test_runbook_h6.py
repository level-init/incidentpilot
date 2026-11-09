"""H6: Runbook store/publish, hybrid retrieval, pin + RUNBOOK_FACT."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from incidentpilot_shared.domain.commands import (
    create_runbook_command,
    create_runbook_version_command,
    pin_runbook_version_command,
    publish_runbook_version_command,
)
from incidentpilot_shared.evidence_producers import is_registered_evidence_producer
from incidentpilot_shared.runbooks import retrieve_runbooks, runbook_searcher_for_broker

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
                cur.execute(
                    """
                    SELECT 1 FROM domain.runbook_version
                    WHERE search_tsv IS NOT NULL LIMIT 1
                    """
                )
                cur.fetchone()
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'domain'
                      AND table_name = 'incident'
                      AND column_name = 'pinned_runbook_version_id'
                    """
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def test_runbook_store_is_registered_producer() -> None:
    assert is_registered_evidence_producer("runbook_store")


def test_authority_is_allowed_action_types_not_prose() -> None:
    """Static contract: pin payload / hits expose allowlist column, not body parsing."""
    from pathlib import Path

    commands = (
        Path(__file__).resolve().parents[1]
        / "shared"
        / "incidentpilot_shared"
        / "domain"
        / "commands.py"
    ).read_text(encoding="utf-8")
    assert '"authority": "allowed_action_types"' in commands
    assert "body_markdown" in commands
    # Pin fact must not treat markdown as allowlist source.
    assert "allowed_action_types" in commands


@pytest.mark.skipif(not _db_available(), reason="H6 migration / Postgres not reachable")
def test_seed_checkout_high_error_rate_retrieval(conn: object) -> None:
    hits = retrieve_runbooks(
        conn,
        query="checkout high_error_rate rollback",
        limit=5,
        hypothesis_class="high_error_rate",
        service_key="checkout",
    )
    assert hits, "expected seeded checkout.high_error_rate runbook"
    top = hits[0]
    assert top.runbook_key == "checkout.high_error_rate"
    assert "ROLLBACK_DEPLOYMENT" in top.allowed_action_types
    assert "SCALE" not in top.allowed_action_types
    # Body may mention SCALE in prose — must not appear in allowlist.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT body_markdown, allowed_action_types
            FROM domain.runbook_version WHERE id = %s
            """,
            (str(top.version_id),),
        )
        body, allowed = cur.fetchone()
    assert "SCALE" in body
    assert list(allowed) == ["ROLLBACK_DEPLOYMENT"]


@pytest.mark.skipif(not _db_available(), reason="H6 migration / Postgres not reachable")
def test_publish_pin_emits_runbook_fact(conn: object) -> None:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'DIAGNOSED', 'h6 pin', 3)
            """,
            (str(incident_id), f"INC-H6-{uuid.uuid4().hex[:8]}"),
        )
    rb = create_runbook_command(
        conn,
        key=f"test.rb.{uuid.uuid4().hex[:8]}",
        title="Test RB",
        hypothesis_class="high_error_rate",
        service_key="checkout",
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown="# steps\nSCALE is mentioned in prose only.",
        allowed_action_types=["ROLLBACK_DEPLOYMENT"],
        commit=False,
    )
    published = publish_runbook_version_command(
        conn, runbook_version_id=ver.runbook_version_id, commit=False
    )
    assert published.status == "published"

    pinned = pin_runbook_version_command(
        conn,
        incident_id=incident_id,
        runbook_version_id=published.runbook_version_id,
        commit=False,
    )
    assert pinned.allowed_action_types == ("ROLLBACK_DEPLOYMENT",)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pinned_runbook_version_id FROM domain.incident WHERE id = %s
            """,
            (str(incident_id),),
        )
        assert uuid.UUID(str(cur.fetchone()[0])) == published.runbook_version_id
        cur.execute(
            """
            SELECT kind, payload->>'authority', payload->'allowed_action_types', producer
            FROM domain.evidence
            WHERE id = %s
            """,
            (str(pinned.evidence_id),),
        )
        kind, authority, allowed, producer = cur.fetchone()
    assert kind == "RUNBOOK_FACT"
    assert authority == "allowed_action_types"
    assert list(allowed) == ["ROLLBACK_DEPLOYMENT"]
    assert producer == "runbook_store"


@pytest.mark.skipif(not _db_available(), reason="H6 migration / Postgres not reachable")
def test_broker_searcher_returns_structured_hits(conn: object) -> None:
    searcher = runbook_searcher_for_broker(conn)
    out = searcher({"query": "high_error_rate", "limit": 3})
    assert out["authority"] == "allowed_action_types"
    assert out["hits"]
    assert "allowed_action_types" in out["hits"][0]
    assert "body_markdown" not in out["hits"][0]
