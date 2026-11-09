"""H2: Minimum AIInvocation provenance records."""

from __future__ import annotations

import ast
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field

from incidentpilot_adapters.llm import (
    FakeLLMProvider,
    LLMMessage,
    LLMRequest,
    StructuredOutputError,
    json_response,
)
from incidentpilot_shared.ai_invocation import complete_structured_recorded
from incidentpilot_shared.domain.commands import record_ai_invocation_command

psycopg = pytest.importorskip("psycopg")

ROOT = Path(__file__).resolve().parents[1]


class HypothesisProposeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    cited_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


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
                cur.execute("SELECT 1 FROM domain.ai_invocation LIMIT 1")
            return True
    except Exception:
        return False


@pytest.fixture()
def conn() -> Iterator[object]:
    with psycopg.connect(_dsn(), autocommit=False) as connection:
        yield connection
        connection.rollback()


def _insert_incident(conn: object) -> uuid.UUID:
    incident_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domain.incident (id, public_id, state, title, incident_revision)
            VALUES (%s, %s, 'INVESTIGATING', 'ai invocation', 1)
            """,
            (str(incident_id), f"INC-AI-{uuid.uuid4().hex[:8]}"),
        )
    return incident_id


def _request(incident_id: uuid.UUID) -> LLMRequest:
    return LLMRequest(
        purpose="hypothesis_propose",
        messages=[LLMMessage(role="user", content="rank hypotheses")],
        response_model=HypothesisProposeOut,
        allowed_evidence_ids=frozenset({"EV-abc123def456"}),
        incident_id=str(incident_id),
        prompt_version="h2.v1",
    )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_record_ai_invocation_command_links_incident(conn: object) -> None:
    incident_id = _insert_incident(conn)
    result = record_ai_invocation_command(
        conn,
        purpose="hypothesis_propose",
        provider="fake",
        model="fake-test",
        status="succeeded",
        incident_id=incident_id,
        prompt_version="h2.v1",
        input_evidence_ids=["EV-abc123def456"],
        prompt_hash="ph",
        response_hash="rh",
        commit=False,
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT purpose, provider, model, status, incident_id,
                   request_metadata, created_at
            FROM domain.ai_invocation
            WHERE id = %s
            """,
            (str(result.invocation_id),),
        )
        row = cur.fetchone()
    assert row is not None
    purpose, provider, model, status, linked, meta, created_at = row
    assert purpose == "hypothesis_propose"
    assert provider == "fake"
    assert model == "fake-test"
    assert status == "succeeded"
    assert uuid.UUID(str(linked)) == incident_id
    assert created_at is not None
    payload = meta if isinstance(meta, dict) else json.loads(meta)
    assert payload["prompt_version"] == "h2.v1"
    assert payload["input_evidence_ids"] == ["EV-abc123def456"]


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_complete_structured_recorded_writes_row(conn: object) -> None:
    incident_id = _insert_incident(conn)
    provider = FakeLLMProvider(
        responses=[
            json_response(
                {
                    "statement": "bad deploy on payment",
                    "cited_evidence_ids": ["EV-abc123def456"],
                    "confidence": 0.8,
                }
            )
        ]
    )
    llm_result, recorded = complete_structured_recorded(
        conn, provider, _request(incident_id), commit=False
    )
    assert llm_result.status == "succeeded"
    assert recorded.status == "succeeded"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT model, status, incident_id, request_metadata->>'prompt_version',
                   request_metadata->'input_evidence_ids'
            FROM domain.ai_invocation
            WHERE id = %s
            """,
            (str(recorded.invocation_id),),
        )
        row = cur.fetchone()
    assert row is not None
    model, status, linked, prompt_version, evidence_ids = row
    assert model == "fake-test"
    assert status == "succeeded"
    assert uuid.UUID(str(linked)) == incident_id
    assert prompt_version == "h2.v1"
    ids = evidence_ids if isinstance(evidence_ids, list) else json.loads(evidence_ids)
    assert ids == ["EV-abc123def456"]


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_failed_validation_still_writes_provenance(conn: object) -> None:
    incident_id = _insert_incident(conn)
    provider = FakeLLMProvider(responses=["this is prose, not JSON"])
    with pytest.raises(StructuredOutputError, match="not valid JSON"):
        complete_structured_recorded(conn, provider, _request(incident_id), commit=False)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, error_summary IS NOT NULL, incident_id
            FROM domain.ai_invocation
            WHERE incident_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
    assert row is not None
    status, has_error, linked = row
    assert status == "failed"
    assert has_error is True
    assert uuid.UUID(str(linked)) == incident_id


def test_adapters_llm_still_free_of_domain_commands() -> None:
    llm_root = ROOT / "adapters" / "incidentpilot_adapters" / "llm"
    for path in llm_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "domain.commands" not in node.module
                assert node.module != "incidentpilot_shared.domain.commands"
