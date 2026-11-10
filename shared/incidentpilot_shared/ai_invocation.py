"""Record AIInvocation provenance for each structured LLM call (H2 + L3).

Adapters never write ``domain.*``. Workers/API call ``complete_structured_recorded``
so every reasoning attempt (success or validation failure) leaves a row.
L3 best-effort uploads prompt/tool packages to S3 and sets ``artifact_uri``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from incidentpilot_shared.ai_artifacts import (
    build_ai_invocation_artifact_package,
    new_invocation_id,
    upload_ai_invocation_artifact,
)
from incidentpilot_shared.domain.commands import (
    RecordAiInvocationResult,
    record_ai_invocation_command,
)

if TYPE_CHECKING:
    from psycopg import Connection

    from incidentpilot_adapters.blob.protocol import BlobStore
    from incidentpilot_adapters.llm.protocol import LLMProvider, LLMRequest, LLMResult


@dataclass(frozen=True, slots=True)
class AiInvocationProvenance:
    """Read model for Admin provenance API (L3)."""

    invocation_id: UUID
    incident_id: UUID | None
    purpose: str
    provider: str
    model: str
    status: str
    prompt_version: str | None
    input_evidence_ids: tuple[str, ...]
    artifact_uri: str | None
    request_metadata: dict[str, Any]
    response_metadata: dict[str, Any]
    error_summary: str | None
    created_at: datetime
    prompt_hash: str | None = None
    response_hash: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None


def record_from_llm_result(
    conn: Connection,
    result: LLMResult,
    *,
    request: LLMRequest | None = None,
    blob_store: BlobStore | None = None,
    invocation_id: UUID | None = None,
    commit: bool = True,
) -> RecordAiInvocationResult:
    """Persist one ``domain.ai_invocation`` from an ``LLMResult`` (+ L3 artifact)."""
    purpose = result.purpose or (request.purpose if request else "unknown")
    incident_id = result.incident_id or (request.incident_id if request else None)
    prompt_version = result.prompt_version or (request.prompt_version if request else None)
    if result.input_evidence_ids:
        evidence_ids: list[str] | tuple[str, ...] = result.input_evidence_ids
    elif request is not None:
        evidence_ids = tuple(sorted(request.allowed_evidence_ids))
    else:
        evidence_ids = ()

    inv_id = invocation_id or new_invocation_id()
    package = build_ai_invocation_artifact_package(
        invocation_id=inv_id,
        result=result,
        request=request,
    )
    store = blob_store
    if store is None:
        try:
            from incidentpilot_adapters.blob import resolve_ai_artifacts_blob_store

            store = resolve_ai_artifacts_blob_store()
        except Exception:  # noqa: BLE001 — adapters optional at import time
            store = None
    upload = upload_ai_invocation_artifact(
        store,
        invocation_id=inv_id,
        package=package,
        incident_id=str(incident_id) if incident_id else None,
    )

    response_meta: dict[str, Any] = {
        "has_parsed": result.parsed is not None,
        "tool_calls": list(result.tool_calls) if result.tool_calls else [],
        "artifact_blob_status": upload.blob_status,
    }
    if upload.blob_error:
        response_meta["artifact_blob_error"] = upload.blob_error
    if upload.sha256:
        response_meta["artifact_sha256"] = upload.sha256

    return record_ai_invocation_command(
        conn,
        purpose=purpose,
        provider=result.provider,
        model=result.model,
        status=result.status,
        incident_id=incident_id,
        prompt_hash=result.prompt_hash,
        response_hash=result.response_hash,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_ms=result.latency_ms,
        error_summary=result.error_summary,
        prompt_version=prompt_version,
        input_evidence_ids=evidence_ids,
        response_metadata=response_meta,
        artifact_uri=upload.artifact_uri,
        invocation_id=inv_id,
        commit=commit,
    )


def complete_structured_recorded(
    conn: Connection,
    provider: LLMProvider,
    request: LLMRequest,
    *,
    blob_store: BlobStore | None = None,
    commit: bool = True,
) -> tuple[LLMResult, RecordAiInvocationResult]:
    """H1 complete + H2/L3 provenance — always writes a row, even on validation failure.

    Re-raises ``StructuredOutputError`` after the failed row is persisted.
    """
    from incidentpilot_adapters.llm.validate import (
        StructuredOutputError,
        validate_structured_result,
    )

    result = provider.complete(request)
    if not result.purpose:
        result.purpose = request.purpose
    if result.incident_id is None:
        result.incident_id = request.incident_id
    if result.prompt_version is None:
        result.prompt_version = request.prompt_version
    if not result.input_evidence_ids:
        result.input_evidence_ids = tuple(sorted(request.allowed_evidence_ids))

    error: StructuredOutputError | None = None
    if result.status == "succeeded":
        try:
            result = validate_structured_result(request, result)
        except StructuredOutputError as exc:
            error = exc

    recorded = record_from_llm_result(
        conn,
        result,
        request=request,
        blob_store=blob_store,
        commit=commit,
    )
    if error is not None:
        raise StructuredOutputError(str(error)) from error
    return result, recorded


def get_ai_invocation_provenance(
    conn: Connection,
    *,
    invocation_id: UUID,
) -> AiInvocationProvenance | None:
    """Load provenance for one AIInvocation (input Evidence lineage + outputs)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, incident_id, purpose, provider, model, status,
                   artifact_uri, request_metadata, response_metadata,
                   error_summary, created_at, prompt_hash, response_hash,
                   input_tokens, output_tokens, latency_ms
            FROM domain.ai_invocation
            WHERE id = %s
            """,
            (str(invocation_id),),
        )
        row = cur.fetchone()
    if row is None:
        return None
    (
        inv_id,
        incident_id,
        purpose,
        provider,
        model,
        status,
        artifact_uri,
        request_metadata,
        response_metadata,
        error_summary,
        created_at,
        prompt_hash,
        response_hash,
        input_tokens,
        output_tokens,
        latency_ms,
    ) = row
    req_meta = (
        request_metadata
        if isinstance(request_metadata, dict)
        else dict(request_metadata or {})
    )
    resp_meta = (
        response_metadata
        if isinstance(response_metadata, dict)
        else dict(response_metadata or {})
    )
    raw_ids = req_meta.get("input_evidence_ids") or []
    if not isinstance(raw_ids, list):
        raw_ids = []
    return AiInvocationProvenance(
        invocation_id=UUID(str(inv_id)),
        incident_id=UUID(str(incident_id)) if incident_id is not None else None,
        purpose=str(purpose),
        provider=str(provider),
        model=str(model),
        status=str(status),
        prompt_version=(
            str(req_meta["prompt_version"])
            if req_meta.get("prompt_version") is not None
            else None
        ),
        input_evidence_ids=tuple(str(x) for x in raw_ids),
        artifact_uri=str(artifact_uri) if artifact_uri else None,
        request_metadata=req_meta,
        response_metadata=resp_meta,
        error_summary=str(error_summary) if error_summary else None,
        created_at=created_at,
        prompt_hash=str(prompt_hash) if prompt_hash else None,
        response_hash=str(response_hash) if response_hash else None,
        input_tokens=int(input_tokens) if input_tokens is not None else None,
        output_tokens=int(output_tokens) if output_tokens is not None else None,
        latency_ms=int(latency_ms) if latency_ms is not None else None,
    )
