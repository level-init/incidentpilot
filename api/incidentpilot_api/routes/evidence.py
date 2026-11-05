"""EvidenceProducer write API (G1) — registered producers only."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from incidentpilot_api.commands import append_evidence_command
from incidentpilot_api.db import get_conn
from incidentpilot_api.schemas import EvidenceOut
from incidentpilot_shared.evidence_producers import (
    EvidenceProducerDenied,
    assert_registered_evidence_producer,
)

router = APIRouter(tags=["evidence"])

_VALID_KINDS = frozenset(
    {
        "METRIC",
        "LOG",
        "TRACE",
        "CHANGE",
        "ACTION_RESULT",
        "HUMAN_OBSERVATION",
        "ALERT_CONTEXT",
        "OTHER",
    }
)


class EvidenceProduceBody(BaseModel):
    kind: str
    fingerprint: str = Field(min_length=1, max_length=512)
    summary: str = Field(min_length=1, max_length=4000)
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


def require_evidence_producer(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Bind producer identity from ``Authorization: Bearer producer:<name>``.

    Never accept ``producer`` from the JSON body (spoof-resistant).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Bearer token; use producer:<registered_name>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token.startswith("producer:"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="evidence write requires Bearer producer:<registered_name>",
        )
    name = token.removeprefix("producer:").strip()
    try:
        return assert_registered_evidence_producer(name)
    except EvidenceProducerDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.post(
    "/incidents/{incident_id}/evidence",
    response_model=EvidenceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Produce Evidence (registered producers)",
)
def produce_evidence(
    incident_id: UUID,
    body: EvidenceProduceBody,
    response: Response,
    producer: Annotated[str, Depends(require_evidence_producer)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> EvidenceOut:
    """Idempotent Evidence write by registered producer.

    Duplicate ``(incident_id, fingerprint)`` returns the existing row with **200**.
    """
    if body.kind not in _VALID_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid kind; expected one of {sorted(_VALID_KINDS)}",
        )
    fp = body.fingerprint.strip()
    if not fp.startswith(f"{producer}:"):
        fp = f"{producer}:{fp}"

    try:
        result = append_evidence_command(
            conn,
            incident_id=incident_id,
            kind=body.kind,
            fingerprint=fp,
            summary=body.summary,
            producer=producer,
            payload=body.payload,
            provenance={**body.provenance, "producer": producer},
            commit=True,
        )
    except EvidenceProducerDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    if not result.inserted:
        response.status_code = status.HTTP_200_OK

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, evidence_key, incident_id, kind, summary, fingerprint,
                   observed_at, producer
            FROM domain.evidence WHERE id = %s
            """,
            (str(result.evidence_id),),
        )
        row = cur.fetchone()
    assert row is not None
    return EvidenceOut(**row)
