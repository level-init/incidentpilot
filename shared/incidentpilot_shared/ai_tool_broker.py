"""AI tool broker — READ / PROPOSE / COLLECTOR_TRIGGER only (H3).

Enforces C5 (registry deny) + C6 (``ToolScope``). Evidence reads go through
redacted projections only. Never POLICY_EVAL or ACTION_EXECUTE.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from incidentpilot_shared.ai_tools import (
    AI_SANDBOX_IDENTITY,
    DENIED_TOOL_NAMES,
    AiToolRegistry,
    ToolCapability,
    ToolDeniedError,
    default_ai_tool_registry,
)
from incidentpilot_shared.evidence_projections import read_evidence_projection_for_llm
from incidentpilot_shared.redaction import EvidenceProjection
from incidentpilot_shared.tool_scope import ToolScope

if TYPE_CHECKING:
    from psycopg import Connection


class TelemetryExplorer(Protocol):
    """Exploratory telemetry — never Evidence authorship; no Prom/Loki/Tempo creds."""

    def explore(
        self,
        *,
        incident_id: str,
        environment: str,
        query: str,
        window_seconds: int,
    ) -> Mapping[str, Any]: ...


CollectorTriggerFn = Callable[[dict[str, Any]], Mapping[str, Any]]
RunbookSearchFn = Callable[[dict[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    tool_name: str
    capability: ToolCapability
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class AiToolBroker:
    """Capability-scoped invoke gate for ``AI_SANDBOX_IDENTITY``."""

    def __init__(
        self,
        *,
        scope: ToolScope,
        registry: AiToolRegistry | None = None,
        conn: Connection | None = None,
        telemetry_explorer: TelemetryExplorer | None = None,
        collector_trigger: CollectorTriggerFn | None = None,
        runbook_searcher: RunbookSearchFn | None = None,
    ) -> None:
        self._scope = scope
        self._registry = registry or default_ai_tool_registry()
        self._conn = conn
        self._telemetry_explorer = telemetry_explorer
        self._collector_trigger = collector_trigger
        self._runbook_searcher = runbook_searcher

    @property
    def scope(self) -> ToolScope:
        return self._scope

    @property
    def identity(self) -> str:
        return AI_SANDBOX_IDENTITY

    def schemas_for_llm(self) -> dict[str, dict[str, Any]]:
        return self._registry.json_schemas()

    def invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        resource_owner_incident_id: str | None = None,
        resource_environment: str | None = None,
        resource_id: str | None = None,
    ) -> ToolInvocationResult:
        """Validate + dispatch. Denied / unknown tools never reach handlers."""
        if tool_name in DENIED_TOOL_NAMES:
            raise ToolDeniedError(
                f"tool {tool_name!r} is denied for identity {AI_SANDBOX_IDENTITY}"
            )

        spec = self._registry.require_allowed(tool_name)
        if spec.capability not in (
            ToolCapability.READ,
            ToolCapability.PROPOSE,
            ToolCapability.COLLECTOR_TRIGGER,
        ):
            raise ToolDeniedError(
                f"capability {spec.capability!r} unavailable to identity {AI_SANDBOX_IDENTITY}"
            )

        validated = self._registry.validate_scoped_invocation(
            self._scope,
            tool_name,
            arguments,
            resource_owner_incident_id=resource_owner_incident_id,
            resource_environment=resource_environment,
            resource_id=resource_id,
        )

        data = self._dispatch(tool_name, validated)
        return ToolInvocationResult(
            tool_name=tool_name,
            capability=spec.capability,
            ok=True,
            data=dict(data),
        )

    def _dispatch(self, tool_name: str, args: dict[str, Any]) -> Mapping[str, Any]:
        if tool_name == "telemetry_read":
            return self._telemetry_read(args)
        if tool_name == "evidence_projection_read":
            return self._evidence_projection_read(args)
        if tool_name == "runbook_search":
            return self._runbook_search(args)
        if tool_name == "hypothesis_propose":
            return {"proposal": args, "executed": False}
        if tool_name == "action_propose":
            # Propose only — never remediation execution or policy authorization.
            return {"proposal": args, "executed": False, "authorized": False}
        if tool_name == "collector_trigger":
            return self._collector_trigger_invoke(args)
        raise ToolDeniedError(
            f"tool {tool_name!r} has no broker handler for identity {AI_SANDBOX_IDENTITY}"
        )

    def _telemetry_read(self, args: dict[str, Any]) -> Mapping[str, Any]:
        if self._telemetry_explorer is None:
            # Exploratory guidance without Prom/Loki/Tempo credentials on general.
            return {
                "mode": "exploratory",
                "evidence_authorship": False,
                "hint": "use collector_trigger to schedule evidence-worker collect",
                "query": args["query"],
                "window_seconds": args["window_seconds"],
                "samples": [],
            }
        explored = dict(
            self._telemetry_explorer.explore(
                incident_id=str(args["incident_id"]),
                environment=self._scope.environment,
                query=str(args["query"]),
                window_seconds=int(args["window_seconds"]),
            )
        )
        explored["evidence_authorship"] = False
        return explored

    def _evidence_projection_read(self, args: dict[str, Any]) -> Mapping[str, Any]:
        if self._conn is None:
            raise RuntimeError("evidence_projection_read requires a database connection")
        projection: EvidenceProjection = read_evidence_projection_for_llm(
            self._conn,
            incident_id=UUID(str(args["incident_id"])),
            evidence_id=UUID(str(args["evidence_id"])),
        )
        return {
            "summary": projection.summary,
            "structured_data": projection.structured_data,
            "redacted_fields": list(projection.redacted_fields),
            "source": "evidence_projection",
        }

    def _runbook_search(self, args: dict[str, Any]) -> Mapping[str, Any]:
        if self._runbook_searcher is not None:
            return self._runbook_searcher(args)
        return {"query": args["query"], "hits": [], "limit": args.get("limit", 5)}

    def _collector_trigger_invoke(self, args: dict[str, Any]) -> Mapping[str, Any]:
        if self._collector_trigger is None:
            raise RuntimeError("collector_trigger handler is not configured")
        payload = {
            "incident_id": str(args["incident_id"]),
            "environment": self._scope.environment,
            "collector": str(args["collector"]),
            "query": str(args["query"]),
        }
        return self._collector_trigger(payload)


def invoke_ai_tool(
    broker: AiToolBroker,
    tool_name: str,
    arguments: dict[str, Any],
    **kwargs: Any,
) -> ToolInvocationResult:
    """Module-level entry for workers/tests."""
    return broker.invoke(tool_name, arguments, **kwargs)
