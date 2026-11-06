"""H1: LLM provider abstraction + structured output validation."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from incidentpilot_adapters.llm import (
    FakeLLMProvider,
    LLMMessage,
    LLMRequest,
    StructuredOutputError,
    complete_structured,
    json_response,
    resolve_llm_provider,
)

ROOT = Path(__file__).resolve().parents[1]


class HypothesisProposeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    cited_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


def _request(
    *,
    allowed: frozenset[str] | None = None,
    purpose: str = "hypothesis_propose",
) -> LLMRequest:
    return LLMRequest(
        purpose=purpose,
        messages=[LLMMessage(role="user", content="rank hypotheses")],
        response_model=HypothesisProposeOut,
        allowed_evidence_ids=allowed or frozenset({"EV-abc123def456"}),
        incident_id="inc-1",
        prompt_version="h1.v1",
    )


def test_valid_structured_output_parses() -> None:
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
    result = complete_structured(provider, _request())
    assert result.status == "succeeded"
    assert result.parsed is not None
    assert result.parsed.statement.startswith("bad deploy")
    assert result.provider == "fake"
    assert result.model == "fake-test"
    assert result.prompt_hash
    assert result.response_hash
    assert result.input_tokens is not None
    assert result.purpose == "hypothesis_propose"


def test_invalid_json_rejected() -> None:
    provider = FakeLLMProvider(responses=["this is prose, not JSON"])
    with pytest.raises(StructuredOutputError, match="not valid JSON"):
        complete_structured(provider, _request())


def test_extra_fields_rejected() -> None:
    provider = FakeLLMProvider(
        responses=[
            json_response(
                {
                    "statement": "x",
                    "cited_evidence_ids": ["EV-abc123def456"],
                    "confidence": 0.5,
                    "sneaky_mutate": True,
                }
            )
        ]
    )
    with pytest.raises(StructuredOutputError):
        complete_structured(provider, _request())


def test_invented_evidence_ids_rejected() -> None:
    provider = FakeLLMProvider(
        responses=[
            json_response(
                {
                    "statement": "invented cite",
                    "cited_evidence_ids": ["EV-not-real-0000"],
                    "confidence": 0.9,
                }
            )
        ]
    )
    with pytest.raises(StructuredOutputError, match="invented evidence id"):
        complete_structured(provider, _request())


def test_failed_validation_does_not_import_domain_commands() -> None:
    """Prose / invalid output must not open a domain mutation path."""
    provider = FakeLLMProvider(responses=["not-json"])
    with pytest.raises(StructuredOutputError):
        complete_structured(provider, _request())
    # Adapter package must stay free of domain command imports (B7).
    llm_root = ROOT / "adapters" / "incidentpilot_adapters" / "llm"
    for path in llm_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "domain.commands" not in node.module
                assert node.module != "incidentpilot_shared.domain.commands"


def test_resolve_default_is_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    provider = resolve_llm_provider()
    assert provider.name == "fake"


def test_resolve_unknown_provider_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    with pytest.raises(RuntimeError, match="not configured"):
        resolve_llm_provider()


def test_literal_status_values() -> None:
    statuses: tuple[Literal["succeeded", "failed", "timeout", "cancelled"], ...] = (
        "succeeded",
        "failed",
        "timeout",
        "cancelled",
    )
    assert "failed" in statuses
