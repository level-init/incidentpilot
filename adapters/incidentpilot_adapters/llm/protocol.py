"""LLMProvider protocol — outbound complete; no domain writes (H1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

LLMStatus = Literal["succeeded", "failed", "timeout", "cancelled"]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: str
    content: str


@dataclass
class LLMRequest:
    """Chat-style request with a pydantic response schema."""

    purpose: str
    messages: list[LLMMessage]
    response_model: type[BaseModel]
    allowed_evidence_ids: frozenset[str] = field(default_factory=frozenset)
    incident_id: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    tools: list[dict[str, Any]] | None = None


@dataclass
class LLMResult:
    """Provider-agnostic result shaped for ``domain.ai_invocation`` (H2 persists)."""

    provider: str
    model: str
    status: LLMStatus
    raw_text: str = ""
    parsed: BaseModel | None = None
    prompt_hash: str | None = None
    response_hash: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    error_summary: str | None = None
    prompt_version: str | None = None
    input_evidence_ids: tuple[str, ...] = ()
    tool_calls: list[dict[str, Any]] | None = None
    purpose: str = ""
    incident_id: str | None = None


class LLMProvider(Protocol):
    """Outbound LLM client. Must never write ``domain.*``."""

    name: str

    def complete(self, request: LLMRequest) -> LLMResult:
        """Return a raw completion (may be invalid JSON — validation is separate)."""
        ...
