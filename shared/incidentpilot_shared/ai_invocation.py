"""Record AIInvocation provenance for each structured LLM call (H2).

Adapters never write ``domain.*``. Workers/API call ``complete_structured_recorded``
so every reasoning attempt (success or validation failure) leaves a row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from incidentpilot_shared.domain.commands import (
    RecordAiInvocationResult,
    record_ai_invocation_command,
)

if TYPE_CHECKING:
    from psycopg import Connection

    from incidentpilot_adapters.llm.protocol import LLMProvider, LLMRequest, LLMResult


def record_from_llm_result(
    conn: Connection,
    result: LLMResult,
    *,
    request: LLMRequest | None = None,
    commit: bool = True,
) -> RecordAiInvocationResult:
    """Persist one ``domain.ai_invocation`` from an ``LLMResult``."""
    purpose = result.purpose or (request.purpose if request else "unknown")
    incident_id = result.incident_id or (request.incident_id if request else None)
    prompt_version = result.prompt_version or (request.prompt_version if request else None)
    if result.input_evidence_ids:
        evidence_ids: list[str] | tuple[str, ...] = result.input_evidence_ids
    elif request is not None:
        evidence_ids = tuple(sorted(request.allowed_evidence_ids))
    else:
        evidence_ids = ()
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
        response_metadata={"has_parsed": result.parsed is not None},
        commit=commit,
    )


def complete_structured_recorded(
    conn: Connection,
    provider: LLMProvider,
    request: LLMRequest,
    *,
    commit: bool = True,
) -> tuple[LLMResult, RecordAiInvocationResult]:
    """H1 complete + H2 provenance — always writes a row, even on validation failure.

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

    recorded = record_from_llm_result(conn, result, request=request, commit=commit)
    if error is not None:
        raise StructuredOutputError(str(error)) from error
    return result, recorded
