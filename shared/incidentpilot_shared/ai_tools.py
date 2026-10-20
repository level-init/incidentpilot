"""AI tool schemas + deny matrix (C5).

Capability-scoped tools for the AI sandbox identity. Ops RBAC roles are not
trust: the sandbox may only invoke the fixed allow-list (READ / PROPOSE).
Forbidden capabilities (ACTION_EXECUTE, POLICY_EVAL, GroundTruth, shell /
kubectl / SQL, secrets) are never registered and are rejected on lookup.

H3 will broker these tools; this module only defines schemas + deny policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ToolDeniedError(Exception):
    """Raised when the AI sandbox requests a forbidden or unregistered tool."""


class ToolSchemaError(Exception):
    """Raised when tool arguments fail fixed-schema validation (incl. extras)."""


class ToolCapability(StrEnum):
    """Capabilities the AI sandbox may hold. EXECUTE / POLICY / GT are absent."""

    READ = "READ"
    PROPOSE = "PROPOSE"
    COLLECTOR_TRIGGER = "COLLECTOR_TRIGGER"


# Explicit deny matrix — never available to AI sandbox identity (roles ≠ trust).
DENIED_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "ACTION_EXECUTE",
        "action_execute",
        "POLICY_EVAL",
        "policy_eval",
        "GROUND_TRUTH",
        "ground_truth",
        "ground_truth_read",
        "GT_READ",
        "gt_read",
        "shell",
        "shell_exec",
        "kubectl",
        "kubectl_exec",
        "sql",
        "sql_query",
        "secrets",
        "secrets_read",
        "secret_read",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TelemetryReadArgs(_StrictModel):
    incident_id: str
    query: str = Field(min_length=1, max_length=2000)
    window_seconds: int = Field(default=300, ge=1, le=86_400)


class EvidenceProjectionReadArgs(_StrictModel):
    incident_id: str
    evidence_id: str


class RunbookSearchArgs(_StrictModel):
    incident_id: str
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)


class HypothesisProposeArgs(_StrictModel):
    incident_id: str
    statement: str = Field(min_length=1, max_length=4000)
    cited_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ActionProposeArgs(_StrictModel):
    """Propose only — ACTION_EXECUTE is denied and not a tool."""

    incident_id: str
    action_type: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=1, max_length=4000)
    parameters: dict[str, Any] = Field(default_factory=dict)


class CollectorTriggerArgs(_StrictModel):
    incident_id: str
    collector: Literal["metrics", "logs", "traces", "changes"]
    query: str = Field(min_length=1, max_length=2000)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    capability: ToolCapability
    description: str
    args_model: type[BaseModel]

    def json_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()


AI_SANDBOX_IDENTITY: Final[str] = "ai_sandbox"


def _default_tools() -> dict[str, ToolSpec]:
    specs = (
        ToolSpec(
            name="telemetry_read",
            capability=ToolCapability.READ,
            description="Exploratory telemetry read (not Evidence authorship).",
            args_model=TelemetryReadArgs,
        ),
        ToolSpec(
            name="evidence_projection_read",
            capability=ToolCapability.READ,
            description="Read redacted Evidence projections for LLM supply.",
            args_model=EvidenceProjectionReadArgs,
        ),
        ToolSpec(
            name="runbook_search",
            capability=ToolCapability.READ,
            description="Search runbooks relevant to the incident.",
            args_model=RunbookSearchArgs,
        ),
        ToolSpec(
            name="hypothesis_propose",
            capability=ToolCapability.PROPOSE,
            description="Propose an evidence-linked hypothesis (interpretation).",
            args_model=HypothesisProposeArgs,
        ),
        ToolSpec(
            name="action_propose",
            capability=ToolCapability.PROPOSE,
            description="Propose a remediation action (never execute).",
            args_model=ActionProposeArgs,
        ),
        ToolSpec(
            name="collector_trigger",
            capability=ToolCapability.COLLECTOR_TRIGGER,
            description="Trigger a bounded collector fetch for the incident.",
            args_model=CollectorTriggerArgs,
        ),
    )
    registry = {spec.name: spec for spec in specs}
    overlap = DENIED_TOOL_NAMES.intersection(registry)
    if overlap:
        raise RuntimeError(f"allow-list intersects deny matrix: {sorted(overlap)}")
    return registry


class AiToolRegistry:
    """Fixed tool registry for the AI sandbox identity."""

    def __init__(self, tools: dict[str, ToolSpec] | None = None) -> None:
        self._tools = dict(tools) if tools is not None else _default_tools()
        overlap = DENIED_TOOL_NAMES.intersection(self._tools)
        if overlap:
            raise ToolDeniedError(f"cannot register denied tools for AI sandbox: {sorted(overlap)}")

    def list_for_ai_sandbox(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda s: s.name)

    def is_allowed(self, tool_name: str) -> bool:
        if tool_name in DENIED_TOOL_NAMES:
            return False
        return tool_name in self._tools

    def require_allowed(self, tool_name: str) -> ToolSpec:
        if tool_name in DENIED_TOOL_NAMES:
            raise ToolDeniedError(
                f"tool {tool_name!r} is denied for identity {AI_SANDBOX_IDENTITY}"
            )
        try:
            return self._tools[tool_name]
        except KeyError as exc:
            raise ToolDeniedError(
                f"tool {tool_name!r} is unavailable to identity {AI_SANDBOX_IDENTITY}"
            ) from exc

    def validate_args(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Validate args against the fixed schema; reject unknown fields."""
        spec = self.require_allowed(tool_name)
        try:
            model = spec.args_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolSchemaError(str(exc)) from exc
        return model.model_dump()

    def json_schemas(self) -> dict[str, dict[str, Any]]:
        return {name: spec.json_schema() for name, spec in sorted(self._tools.items())}


def default_ai_tool_registry() -> AiToolRegistry:
    return AiToolRegistry()
