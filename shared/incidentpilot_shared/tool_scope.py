"""Confused-deputy scope guard for AI tools (C6).

Privileged / AI-sandbox tools must not widen scope via arguments. The server
binds each invocation to a fixed ``ToolScope`` (incident_id + environment) and
rejects cross-incident or cross-environment access. Resource ownership checks
cover evidence / service ids when provided by the broker (H3).

NetworkPolicies are out of scope (Epic O).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

# Product environments (docs/product-overview.md). Aliases normalized below.
KNOWN_ENVIRONMENTS: Final[frozenset[str]] = frozenset(
    {
        "local",
        "test",
        "staging",
        "production-demo",
    }
)

_ENV_ALIASES: Final[dict[str, str]] = {
    "prod-demo": "production-demo",
    "production_demo": "production-demo",
    "prod_demo": "production-demo",
}

# Keys that must not disagree with the bound scope (including nested payloads).
_SCOPE_KEYS_INCIDENT: Final[frozenset[str]] = frozenset(
    {
        "incident_id",
        "incidentId",
    }
)
_SCOPE_KEYS_ENVIRONMENT: Final[frozenset[str]] = frozenset(
    {
        "environment",
        "env",
        "target_environment",
        "target_env",
    }
)


class ScopeViolationError(Exception):
    """Raised when tool args or resources widen beyond the bound ToolScope."""


@dataclass(frozen=True, slots=True)
class ToolScope:
    """Server-bound scope for one AI sandbox / tool invocation context."""

    incident_id: str
    environment: str
    owned_resource_ids: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.incident_id:
            raise ScopeViolationError("ToolScope.incident_id is required")
        normalized = normalize_environment(self.environment)
        object.__setattr__(self, "environment", normalized)


def normalize_environment(environment: str) -> str:
    key = environment.strip().lower()
    key = _ENV_ALIASES.get(key, key)
    if key not in KNOWN_ENVIRONMENTS:
        raise ScopeViolationError(f"unknown environment: {environment!r}")
    return key


def _walk_scope_keys(value: Any, path: str = "") -> list[tuple[str, str, Any]]:
    """Return (path, key, value) for scope-sensitive keys in nested structures."""
    found: list[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            key = str(k)
            child = f"{path}.{key}" if path else key
            if key in _SCOPE_KEYS_INCIDENT or key in _SCOPE_KEYS_ENVIRONMENT:
                found.append((child, key, v))
            found.extend(_walk_scope_keys(v, child))
    elif isinstance(value, list | tuple):
        for i, item in enumerate(value):
            found.extend(_walk_scope_keys(item, f"{path}[{i}]"))
    return found


def enforce_tool_scope(
    scope: ToolScope,
    *,
    arguments: dict[str, Any],
    resource_owner_incident_id: str | None = None,
    resource_environment: str | None = None,
    resource_id: str | None = None,
) -> None:
    """Fail closed if arguments or resources widen beyond ``scope``."""
    arg_incident = arguments.get("incident_id")
    if arg_incident is None:
        raise ScopeViolationError("tool arguments require incident_id")
    if str(arg_incident) != scope.incident_id:
        raise ScopeViolationError(
            f"cross-incident access denied: bound={scope.incident_id!r} requested={arg_incident!r}"
        )

    for path, key, raw in _walk_scope_keys(arguments):
        if key in _SCOPE_KEYS_INCIDENT and str(raw) != scope.incident_id:
            raise ScopeViolationError(
                f"cross-incident access denied at {path}: "
                f"bound={scope.incident_id!r} requested={raw!r}"
            )
        if key in _SCOPE_KEYS_ENVIRONMENT:
            requested_env = normalize_environment(str(raw))
            if requested_env != scope.environment:
                raise ScopeViolationError(
                    f"cross-env access denied at {path}: "
                    f"bound={scope.environment!r} requested={requested_env!r}"
                )

    if resource_owner_incident_id is not None and resource_owner_incident_id != scope.incident_id:
        raise ScopeViolationError(
            f"cross-incident access denied: resource owned by "
            f"{resource_owner_incident_id!r}, bound={scope.incident_id!r}"
        )

    if resource_environment is not None:
        res_env = normalize_environment(resource_environment)
        if res_env != scope.environment:
            raise ScopeViolationError(
                f"cross-env access denied: resource env={res_env!r}, bound={scope.environment!r}"
            )

    if resource_id is not None and scope.owned_resource_ids:
        if resource_id not in scope.owned_resource_ids:
            raise ScopeViolationError(
                f"resource {resource_id!r} is not owned by incident {scope.incident_id!r}"
            )

    # evidence_id / similar: when ownership set is populated, require membership
    evidence_id = arguments.get("evidence_id")
    if evidence_id is not None and scope.owned_resource_ids:
        if str(evidence_id) not in scope.owned_resource_ids:
            raise ScopeViolationError(
                f"resource {evidence_id!r} is not owned by incident {scope.incident_id!r}"
            )
