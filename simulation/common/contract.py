"""Contract helpers: simulation must not expose GroundTruth / root-cause cheats (E1/E6)."""

from __future__ import annotations

from collections.abc import Iterable

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


def path_is_forbidden(path: str) -> bool:
    lowered = path.lower()
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


def scan_apps(apps: Iterable[tuple[str, FastAPI]]) -> list[str]:
    """Return human-readable violations (empty if clean)."""
    violations: list[str] = []
    for name, app in apps:
        for path in iter_route_paths(app):
            if path_is_forbidden(path):
                violations.append(f"{name}: {path}")
    return violations
