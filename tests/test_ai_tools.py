"""C5: AI tool schemas + deny matrix (roles are not trust)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from incidentpilot_shared.ai_tools import (
    AI_SANDBOX_IDENTITY,
    DENIED_TOOL_NAMES,
    AiToolRegistry,
    ToolCapability,
    ToolDeniedError,
    ToolSchemaError,
    ToolSpec,
    default_ai_tool_registry,
)


def test_forbidden_tools_unavailable_to_ai_sandbox() -> None:
    registry = default_ai_tool_registry()
    allowed_names = {spec.name for spec in registry.list_for_ai_sandbox()}

    for denied in DENIED_TOOL_NAMES:
        assert denied not in allowed_names
        assert registry.is_allowed(denied) is False
        with pytest.raises(ToolDeniedError, match=AI_SANDBOX_IDENTITY):
            registry.require_allowed(denied)
        with pytest.raises(ToolDeniedError):
            registry.validate_args(denied, {})


def test_unknown_tool_rejected() -> None:
    registry = default_ai_tool_registry()
    with pytest.raises(ToolDeniedError, match="unavailable"):
        registry.require_allowed("totally_made_up_tool")


def test_unknown_fields_rejected() -> None:
    registry = default_ai_tool_registry()
    with pytest.raises(ToolSchemaError, match="extra"):
        registry.validate_args(
            "telemetry_read",
            {
                "incident_id": "inc-1",
                "query": "rate(http_errors[5m])",
                "sneaky_shell": "kubectl get secrets",
            },
        )


def test_valid_args_accepted_for_allow_listed_tools() -> None:
    registry = default_ai_tool_registry()
    cases: list[tuple[str, dict[str, object]]] = [
        (
            "telemetry_read",
            {"incident_id": "inc-1", "query": "up", "window_seconds": 60},
        ),
        (
            "evidence_projection_read",
            {"incident_id": "inc-1", "evidence_id": "ev-1"},
        ),
        (
            "runbook_search",
            {"incident_id": "inc-1", "query": "rollback checkout"},
        ),
        (
            "hypothesis_propose",
            {
                "incident_id": "inc-1",
                "statement": "bad deploy",
                "cited_evidence_ids": ["ev-1"],
                "confidence": 0.7,
            },
        ),
        (
            "action_propose",
            {
                "incident_id": "inc-1",
                "action_type": "rollback",
                "rationale": "error spike after deploy",
                "parameters": {"revision": "prev"},
            },
        ),
        (
            "collector_trigger",
            {
                "incident_id": "inc-1",
                "collector": "logs",
                "query": "{app=checkout}",
            },
        ),
    ]
    for name, args in cases:
        assert registry.is_allowed(name)
        validated = registry.validate_args(name, args)
        assert validated["incident_id"] == "inc-1"


def test_ai_capabilities_exclude_execute_and_policy() -> None:
    caps = {spec.capability for spec in default_ai_tool_registry().list_for_ai_sandbox()}
    assert ToolCapability.READ in caps
    assert ToolCapability.PROPOSE in caps
    assert "EXECUTE" not in {c.value for c in caps}
    assert "POLICY_EVAL" not in {c.value for c in caps}


def test_cannot_register_denied_tool() -> None:
    class Empty(BaseModel):
        model_config = ConfigDict(extra="forbid")

    with pytest.raises(ToolDeniedError, match="denied"):
        AiToolRegistry(
            {
                "ACTION_EXECUTE": ToolSpec(
                    name="ACTION_EXECUTE",
                    capability=ToolCapability.PROPOSE,
                    description="should never register",
                    args_model=Empty,
                )
            }
        )


def test_json_schemas_are_fixed_objects() -> None:
    schemas = default_ai_tool_registry().json_schemas()
    assert "action_propose" in schemas
    assert "ACTION_EXECUTE" not in schemas
    props = schemas["telemetry_read"]["properties"]
    assert "incident_id" in props
    assert "query" in props
    # Pydantic v2 emits additionalProperties: false for extra='forbid'
    assert schemas["telemetry_read"].get("additionalProperties") is False
