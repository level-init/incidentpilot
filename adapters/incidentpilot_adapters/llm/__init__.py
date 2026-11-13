"""LLM provider adapters — outbound only; no domain writes (H1)."""

from incidentpilot_adapters.llm.factory import resolve_llm_provider
from incidentpilot_adapters.llm.fake import FakeLLMProvider, json_response
from incidentpilot_adapters.llm.gemini import GeminiLLMProvider
from incidentpilot_adapters.llm.protocol import (
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResult,
)
from incidentpilot_adapters.llm.validate import (
    StructuredOutputError,
    complete_structured,
    validate_structured_result,
)

__all__ = [
    "FakeLLMProvider",
    "GeminiLLMProvider",
    "LLMMessage",
    "LLMProvider",
    "LLMRequest",
    "LLMResult",
    "StructuredOutputError",
    "complete_structured",
    "json_response",
    "resolve_llm_provider",
    "validate_structured_result",
]
