"""Contract helpers: simulation must not expose GroundTruth / root-cause cheats (E1/E6).

Scans FastAPI route paths, OpenAPI schema field names, and simulation source AST
for answer-key style identifiers. Denylist definitions in this module are exempt
from the source text/AST name checks that would otherwise self-flag.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

# Substrings that must never appear in sim HTTP paths (case-insensitive).
FORBIDDEN_PATH_MARKERS: tuple[str, ...] = (
    "actual-root-cause",
    "actual_root_cause",
    "ground-truth",
    "ground_truth",
    "/gt/",
    "answer-key",
    "answer_key",
    "root-cause-oracle",
    "root_cause_oracle",
)

# Exact-ish field / identifier tokens banned in OpenAPI properties and model fields.
FORBIDDEN_FIELD_MARKERS: tuple[str, ...] = (
    "actual_root_cause",
    "actual-root-cause",
    "ground_truth",
    "ground-truth",
    "answer_key",
    "answer-key",
    "root_cause_oracle",
    "root-cause-oracle",
    "gt_answer",
    "scenario_answer",
)

# Files that define denylists / rejection sets and may mention markers safely.
_SOURCE_SCAN_ALLOWLIST = frozenset(
    {
        "common/contract.py",
        "common/faults.py",
        "faults/catalog.py",
    }
)


def path_is_forbidden(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in FORBIDDEN_PATH_MARKERS)


def field_is_forbidden(name: str) -> bool:
    lowered = name.lower().replace(" ", "_")
    if lowered in {m.lower() for m in FORBIDDEN_FIELD_MARKERS}:
        return True
    return any(marker in lowered for marker in FORBIDDEN_PATH_MARKERS)


def iter_route_paths(app: FastAPI) -> list[str]:
    paths: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.append(path)
    return paths


def assert_no_forbidden_routes(app: FastAPI, *, service: str) -> None:
    bad = [p for p in iter_route_paths(app) if path_is_forbidden(p)]
    if bad:
        raise AssertionError(f"{service} exposes forbidden routes: {bad}")


def _walk_schema_property_names(node: Any, *, prefix: str = "") -> list[str]:
    found: list[str] = []
    if not isinstance(node, dict):
        return found
    props = node.get("properties")
    if isinstance(props, dict):
        for key, child in props.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found.append(path)
            found.extend(_walk_schema_property_names(child, prefix=path))
    for key in ("items", "additionalProperties"):
        if key in node:
            found.extend(_walk_schema_property_names(node[key], prefix=prefix))
    for key in ("oneOf", "anyOf", "allOf"):
        variants = node.get(key)
        if isinstance(variants, list):
            for child in variants:
                found.extend(_walk_schema_property_names(child, prefix=prefix))
    return found


def scan_openapi(app: FastAPI, *, service: str) -> list[str]:
    """Flag forbidden path keys and schema property names in OpenAPI."""
    violations: list[str] = []
    spec = app.openapi()
    for path in spec.get("paths", {}):
        if path_is_forbidden(str(path)):
            violations.append(f"{service} openapi path: {path}")
    components = spec.get("components") or {}
    schemas = components.get("schemas") or {}
    if isinstance(schemas, dict):
        for schema_name, schema in schemas.items():
            if field_is_forbidden(str(schema_name)):
                violations.append(f"{service} openapi schema: {schema_name}")
            for prop_path in _walk_schema_property_names(schema):
                leaf = prop_path.rsplit(".", 1)[-1]
                if field_is_forbidden(leaf):
                    violations.append(f"{service} openapi field: {schema_name}.{prop_path}")
    return violations


def _relative_sim_path(path: Path, sim_root: Path) -> str:
    try:
        return path.relative_to(sim_root).as_posix()
    except ValueError:
        return path.name


def scan_simulation_sources(sim_root: Path | None = None) -> list[str]:
    """AST-scan simulation Python sources for forbidden route strings and field names."""
    root = sim_root or Path(__file__).resolve().parents[1]
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = _relative_sim_path(path, root)
        if rel in _SOURCE_SCAN_ALLOWLIST:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{rel}: syntax error ({exc})")
            continue
        for node in ast.walk(tree):
            # Route decorator string literals: @app.get("/v1/ground_truth")
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if path_is_forbidden(arg.value) or field_is_forbidden(arg.value):
                            violations.append(f"{rel}: literal {arg.value!r}")
                for kw in node.keywords:
                    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        if path_is_forbidden(kw.value.value) or field_is_forbidden(kw.value.value):
                            violations.append(f"{rel}: literal {kw.value.value!r}")
            # AnnAssign field names on models: ground_truth: str
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if field_is_forbidden(node.target.id):
                    violations.append(f"{rel}: field {node.target.id}")
            # Function args that look like answer keys
            if isinstance(node, ast.arg) and field_is_forbidden(node.arg):
                violations.append(f"{rel}: arg {node.arg}")
    return violations


def scan_apps(apps: Iterable[tuple[str, FastAPI]]) -> list[str]:
    """Return human-readable violations (empty if clean)."""
    violations: list[str] = []
    for name, app in apps:
        for path in iter_route_paths(app):
            if path_is_forbidden(path):
                violations.append(f"{name}: {path}")
        violations.extend(scan_openapi(app, service=name))
    return violations


def scan_all(
    sim_root: Path | None = None,
    apps: Iterable[tuple[str, FastAPI]] | None = None,
) -> list[str]:
    """Full E6 contract: routes/OpenAPI (+ optional apps) and source AST."""
    violations: list[str] = []
    if apps is not None:
        violations.extend(scan_apps(apps))
    violations.extend(scan_simulation_sources(sim_root))
    return violations
