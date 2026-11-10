"""L3: AIInvocation S3 artifacts + provenance API (Evidence lineage)."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from incidentpilot_adapters.blob import FailingBlobStore, MemoryBlobStore
from incidentpilot_adapters.llm import FakeLLMProvider, LLMMessage, LLMRequest, json_response
from incidentpilot_api.app import app
from incidentpilot_shared.ai_artifacts import ARTIFACT_SCHEMA
from incidentpilot_shared.ai_invocation import (
    complete_structured_recorded,
    get_ai_invocation_provenance,
)

psycopg = pytest.importorskip("psycopg")


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
            VALUES (%s, %s, 'INVESTIGATING', 'l3 ai artifacts', 1)
            """,
            (str(incident_id), f"INC-L3-{uuid.uuid4().hex[:8]}"),
        )
    return incident_id


def _request(incident_id: uuid.UUID) -> LLMRequest:
    return LLMRequest(
        purpose="hypothesis_propose",
        messages=[LLMMessage(role="user", content="what caused checkout errors?")],
        response_model=HypothesisProposeOut,
        allowed_evidence_ids=frozenset({"EV-abc123def456", "EV-feedfacecafe"}),
        incident_id=str(incident_id),
        prompt_version="l3.v1",
        tools=[{"name": "telemetry_read"}],
    )


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_artifact_upload_and_evidence_lineage(conn: object) -> None:
    """L3 AC: can answer what Evidence IDs were supplied for a recommendation."""
    incident_id = _insert_incident(conn)
    store = MemoryBlobStore(bucket="incidentpilot-ai-artifacts")
    provider = FakeLLMProvider(
        responses=[
            json_response(
                {
                    "statement": "bad deploy",
                    "cited_evidence_ids": ["EV-abc123def456"],
                    "confidence": 0.7,
                }
            )
        ]
    )
    llm_result, recorded = complete_structured_recorded(
        conn,
        provider,
        _request(incident_id),
        blob_store=store,
        commit=False,
    )
    assert llm_result.status == "succeeded"
    assert recorded.artifact_uri is not None
    assert recorded.artifact_uri.startswith("s3://incidentpilot-ai-artifacts/")
    assert set(recorded.input_evidence_ids) == {
        "EV-abc123def456",
        "EV-feedfacecafe",
    }
    assert recorded.artifact_uri in store.objects
    package = json.loads(store.objects[recorded.artifact_uri].decode("utf-8"))
    assert package["schema"] == ARTIFACT_SCHEMA
    assert package["invocation_id"] == str(recorded.invocation_id)
    assert set(package["input_evidence_ids"]) == {
        "EV-abc123def456",
        "EV-feedfacecafe",
    }
    assert package["messages"][0]["content"] == "what caused checkout errors?"
    assert package["tools"] == [{"name": "telemetry_read"}]

    prov = get_ai_invocation_provenance(conn, invocation_id=recorded.invocation_id)
    assert prov is not None
    assert set(prov.input_evidence_ids) == {"EV-abc123def456", "EV-feedfacecafe"}
    assert prov.artifact_uri == recorded.artifact_uri
    assert prov.prompt_version == "l3.v1"
    assert prov.response_metadata.get("artifact_blob_status") == "UPLOADED"


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_upload_failure_still_records_invocation(conn: object) -> None:
    incident_id = _insert_incident(conn)
    provider = FakeLLMProvider(
        responses=[
            json_response(
                {
                    "statement": "x",
                    "cited_evidence_ids": ["EV-abc123def456"],
                    "confidence": 0.5,
                }
            )
        ]
    )
    _, recorded = complete_structured_recorded(
        conn,
        provider,
        _request(incident_id),
        blob_store=FailingBlobStore("s3 down"),
        commit=False,
    )
    assert recorded.status == "succeeded"
    assert recorded.artifact_uri is None
    prov = get_ai_invocation_provenance(conn, invocation_id=recorded.invocation_id)
    assert prov is not None
    assert prov.response_metadata.get("artifact_blob_status") == "UPLOAD_FAILED"
    assert set(prov.input_evidence_ids) == {"EV-abc123def456", "EV-feedfacecafe"}


@pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")
def test_provenance_api_admin_gated(conn: object) -> None:
    incident_id = _insert_incident(conn)
    store = MemoryBlobStore(bucket="incidentpilot-ai-artifacts")
    provider = FakeLLMProvider(
        responses=[
            json_response(
                {
                    "statement": "x",
                    "cited_evidence_ids": ["EV-abc123def456"],
                    "confidence": 0.5,
                }
            )
        ]
    )
    _, recorded = complete_structured_recorded(
        conn,
        provider,
        _request(incident_id),
        blob_store=store,
        commit=True,
    )
    try:
        client = TestClient(app)
        denied = client.get(
            f"/ai-invocations/{recorded.invocation_id}/provenance",
            headers={"Authorization": "Bearer local-dev"},
        )
        assert denied.status_code == 403

        ok = client.get(
            f"/ai-invocations/{recorded.invocation_id}/provenance",
            headers={"Authorization": "Bearer local-dev-admin"},
        )
        assert ok.status_code == 200
        body = ok.json()
        assert body["invocation_id"] == str(recorded.invocation_id)
        assert set(body["input_evidence_ids"]) == {
            "EV-abc123def456",
            "EV-feedfacecafe",
        }
        assert body["artifact_uri"] == recorded.artifact_uri
        assert body["purpose"] == "hypothesis_propose"
    finally:
        with psycopg.connect(_dsn()) as cleanup:
            with cleanup.cursor() as cur:
                cur.execute(
                    "DELETE FROM domain.ai_invocation WHERE id = %s",
                    (str(recorded.invocation_id),),
                )
                cur.execute(
                    "DELETE FROM domain.incident WHERE id = %s",
                    (str(incident_id),),
                )
            cleanup.commit()
