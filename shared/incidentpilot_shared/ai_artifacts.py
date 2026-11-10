"""AIInvocation S3 artifact packages (L3) — prompts, tool traces, evidence lineage.

Adapters own the BlobStore I/O; this module builds the package and orchestrates
upload. Domain persistence stays in ``record_ai_invocation_command``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from incidentpilot_adapters.blob.protocol import BlobStore
    from incidentpilot_adapters.llm.protocol import LLMRequest, LLMResult

ARTIFACT_SCHEMA = "ai_invocation_artifact.v1"


@dataclass(frozen=True, slots=True)
class ArtifactUploadResult:
    artifact_uri: str | None
    blob_status: str
    blob_error: str | None = None
    sha256: str | None = None
    byte_size: int | None = None


def build_ai_invocation_artifact_package(
    *,
    invocation_id: UUID,
    result: LLMResult,
    request: LLMRequest | None = None,
) -> dict[str, Any]:
    """Serialize prompts + tool traces + input Evidence lineage for S3."""
    if result.input_evidence_ids:
        evidence_ids = list(result.input_evidence_ids)
    elif request is not None:
        evidence_ids = sorted(request.allowed_evidence_ids)
    else:
        evidence_ids = []

    messages: list[dict[str, str]] = []
    tools: list[dict[str, Any]] | None = None
    if request is not None:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        tools = list(request.tools) if request.tools else None

    parsed: Any = None
    if result.parsed is not None:
        dump = getattr(result.parsed, "model_dump", None)
        parsed = dump() if callable(dump) else result.parsed

    return {
        "schema": ARTIFACT_SCHEMA,
        "invocation_id": str(invocation_id),
        "purpose": result.purpose or (request.purpose if request else ""),
        "prompt_version": result.prompt_version
        or (request.prompt_version if request else None),
        "provider": result.provider,
        "model": result.model,
        "status": result.status,
        "messages": messages,
        "tools": tools,
        "input_evidence_ids": evidence_ids,
        "tool_calls": list(result.tool_calls) if result.tool_calls else [],
        "raw_text": result.raw_text,
        "parsed": parsed,
        "error_summary": result.error_summary,
        "prompt_hash": result.prompt_hash,
        "response_hash": result.response_hash,
    }


def upload_ai_invocation_artifact(
    blob_store: BlobStore | None,
    *,
    invocation_id: UUID,
    package: dict[str, Any],
    incident_id: str | None = None,
) -> ArtifactUploadResult:
    """Put package to AI artifacts bucket. Never raises — upload is best-effort."""
    if blob_store is None:
        return ArtifactUploadResult(
            artifact_uri=None,
            blob_status="STORE_UNAVAILABLE",
        )
    body = json.dumps(package, sort_keys=True, default=str).encode("utf-8")
    prefix = incident_id or "unscoped"
    key = f"ai-invocations/{prefix}/{invocation_id}.json"
    try:
        put = blob_store.put(key, body, content_type="application/json")
    except Exception as exc:  # noqa: BLE001 — provenance row must still succeed
        return ArtifactUploadResult(
            artifact_uri=None,
            blob_status="UPLOAD_FAILED",
            blob_error=str(exc)[:500],
        )
    return ArtifactUploadResult(
        artifact_uri=put.uri,
        blob_status="UPLOADED",
        sha256=put.sha256,
        byte_size=put.byte_size,
    )


def new_invocation_id() -> UUID:
    return uuid4()
