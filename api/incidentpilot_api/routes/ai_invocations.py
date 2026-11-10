"""L3: AIInvocation provenance API (Admin-gated)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from pydantic import BaseModel, Field

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.db import get_conn
from incidentpilot_api.rbac import Permission, require_permission
from incidentpilot_shared.ai_invocation import get_ai_invocation_provenance

router = APIRouter(tags=["ai-invocations"])


class AiInvocationProvenanceOut(BaseModel):
    invocation_id: UUID
    incident_id: UUID | None = None
    purpose: str
    provider: str
    model: str
    status: str
    prompt_version: str | None = None
    input_evidence_ids: list[str] = Field(default_factory=list)
    artifact_uri: str | None = None
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    response_metadata: dict[str, Any] = Field(default_factory=dict)
    error_summary: str | None = None
    created_at: datetime
    prompt_hash: str | None = None
    response_hash: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None


@router.get(
    "/ai-invocations/{invocation_id}/provenance",
    response_model=AiInvocationProvenanceOut,
)
def get_provenance(
    invocation_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> AiInvocationProvenanceOut:
    """Admin: what Evidence IDs were supplied + outputs / artifact URI (L3)."""
    require_permission(principal, Permission.ADMIN_CONFIG)
    row = get_ai_invocation_provenance(conn, invocation_id=invocation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="ai_invocation not found")
    return AiInvocationProvenanceOut(
        invocation_id=row.invocation_id,
        incident_id=row.incident_id,
        purpose=row.purpose,
        provider=row.provider,
        model=row.model,
        status=row.status,
        prompt_version=row.prompt_version,
        input_evidence_ids=list(row.input_evidence_ids),
        artifact_uri=row.artifact_uri,
        request_metadata=row.request_metadata,
        response_metadata=row.response_metadata,
        error_summary=row.error_summary,
        created_at=row.created_at,
        prompt_hash=row.prompt_hash,
        response_hash=row.response_hash,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        latency_ms=row.latency_ms,
    )
