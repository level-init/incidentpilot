"""Structured-output validation for LLMProvider results (H1).

Rejects invalid JSON, schema violations, and invented Evidence ids.
Never mutates domain state — prose/invalid output cannot invent EV rows.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from incidentpilot_adapters.llm.protocol import LLMProvider, LLMRequest, LLMResult

_EVIDENCE_ID_KEYS = frozenset(
    {
        "cited_evidence_ids",
        "evidence_ids",
        "evidence_id",
        "input_evidence_ids",
    }
)


class StructuredOutputError(ValueError):
    """Raised when structured output fails validation."""


def _walk_evidence_ids(value: Any, path: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_s = str(key)
            child_path = f"{path}.{key_s}" if path else key_s
            if key_s in _EVIDENCE_ID_KEYS:
                if isinstance(child, list | tuple):
                    for i, item in enumerate(child):
                        found.append((f"{child_path}[{i}]", str(item)))
                elif child is not None:
                    found.append((child_path, str(child)))
            found.extend(_walk_evidence_ids(child, child_path))
    elif isinstance(value, list | tuple):
        for i, item in enumerate(value):
            found.extend(_walk_evidence_ids(item, f"{path}[{i}]"))
    return found


def _extract_json_object(raw: str) -> Any:
    text = raw.strip()
    if not text:
        raise StructuredOutputError("empty model response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Allow fenced JSON only — still no free-form prose acceptance.
        match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as exc:
                raise StructuredOutputError(f"invalid fenced JSON: {exc}") from exc
        raise StructuredOutputError("response is not valid JSON") from None


def validate_structured_result(request: LLMRequest, result: LLMResult) -> LLMResult:
    """Parse + schema-validate ``result.raw_text``; check Evidence id allow-list."""
    if result.status != "succeeded":
        return result
    try:
        data = _extract_json_object(result.raw_text)
        model: BaseModel = request.response_model.model_validate(data)
        payload = model.model_dump()
        for path, eid in _walk_evidence_ids(payload):
            if eid not in request.allowed_evidence_ids:
                raise StructuredOutputError(
                    f"invented evidence id at {path}: {eid!r} "
                    f"not in allowed set ({len(request.allowed_evidence_ids)} ids)"
                )
        result.parsed = model
        result.status = "succeeded"
        result.error_summary = None
        return result
    except (StructuredOutputError, ValidationError) as exc:
        result.parsed = None
        result.status = "failed"
        result.error_summary = str(exc)[:500]
        raise StructuredOutputError(str(exc)) from exc


def complete_structured(provider: LLMProvider, request: LLMRequest) -> LLMResult:
    """Call provider then validate — the H1 entrypoint for workers."""
    result = provider.complete(request)
    # Preserve provider failure statuses without re-validating empty bodies.
    if result.status != "succeeded":
        return result
    return validate_structured_result(request, result)
