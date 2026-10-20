"""C6: confused-deputy — incident/env/resource scope on tools."""

from __future__ import annotations

import pytest

from incidentpilot_shared.ai_tools import default_ai_tool_registry
from incidentpilot_shared.tool_scope import (
    ScopeViolationError,
    ToolScope,
    enforce_tool_scope,
    normalize_environment,
)

INC_A = "11111111-1111-1111-1111-111111111111"
INC_B = "22222222-2222-2222-2222-222222222222"


def test_inc_a_cannot_read_inc_b() -> None:
    scope = ToolScope(incident_id=INC_A, environment="staging")
    registry = default_ai_tool_registry()

    with pytest.raises(ScopeViolationError, match="cross-incident"):
        registry.validate_scoped_invocation(
            scope,
            "telemetry_read",
            {"incident_id": INC_B, "query": "up"},
        )


def test_staging_cannot_target_prod_demo() -> None:
    scope = ToolScope(incident_id=INC_A, environment="staging")

    with pytest.raises(ScopeViolationError, match="cross-env"):
        enforce_tool_scope(
            scope,
            arguments={"incident_id": INC_A},
            resource_environment="production-demo",
        )

    # Nested widening via action parameters (confused deputy)
    registry = default_ai_tool_registry()
    with pytest.raises(ScopeViolationError, match="cross-env"):
        registry.validate_scoped_invocation(
            scope,
            "action_propose",
            {
                "incident_id": INC_A,
                "action_type": "rollback",
                "rationale": "try other env",
                "parameters": {"target_environment": "prod-demo"},
            },
        )


def test_cross_incident_resource_ownership_denied() -> None:
    scope = ToolScope(
        incident_id=INC_A,
        environment="staging",
        owned_resource_ids=frozenset({"ev-a"}),
    )
    registry = default_ai_tool_registry()

    with pytest.raises(ScopeViolationError, match="not owned"):
        registry.validate_scoped_invocation(
            scope,
            "evidence_projection_read",
            {"incident_id": INC_A, "evidence_id": "ev-b"},
        )

    with pytest.raises(ScopeViolationError, match="cross-incident"):
        enforce_tool_scope(
            scope,
            arguments={"incident_id": INC_A},
            resource_owner_incident_id=INC_B,
            resource_id="ev-b",
        )


def test_same_scope_allowed() -> None:
    scope = ToolScope(
        incident_id=INC_A,
        environment="staging",
        owned_resource_ids=frozenset({"ev-a"}),
    )
    registry = default_ai_tool_registry()
    validated = registry.validate_scoped_invocation(
        scope,
        "evidence_projection_read",
        {"incident_id": INC_A, "evidence_id": "ev-a"},
        resource_owner_incident_id=INC_A,
        resource_environment="staging",
        resource_id="ev-a",
    )
    assert validated["evidence_id"] == "ev-a"


def test_prod_demo_alias_normalizes() -> None:
    assert normalize_environment("prod-demo") == "production-demo"
    scope = ToolScope(incident_id=INC_A, environment="prod-demo")
    assert scope.environment == "production-demo"


def test_nested_incident_id_widening_denied() -> None:
    scope = ToolScope(incident_id=INC_A, environment="local")
    registry = default_ai_tool_registry()
    with pytest.raises(ScopeViolationError, match="cross-incident"):
        registry.validate_scoped_invocation(
            scope,
            "action_propose",
            {
                "incident_id": INC_A,
                "action_type": "scale",
                "rationale": "pivot",
                "parameters": {"incident_id": INC_B},
            },
        )
