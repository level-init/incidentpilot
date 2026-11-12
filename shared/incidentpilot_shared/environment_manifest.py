"""Capture + pin environment_manifest for ScenarioRuns (N4)."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json


@dataclass(frozen=True)
class EnvironmentManifestView:
    id: UUID
    environment_class: str
    git_sha: str | None
    git_dirty: bool | None
    python_version: str | None
    platform: str | None
    compose_project: str | None
    image_digests: dict[str, Any]
    helm_chart_hash: str | None
    terraform_revision: str | None
    cloud_env_id: str | None
    extras: dict[str, Any]
    captured_at: Any


def _git_probe(repo_root: Path | None = None) -> tuple[str | None, bool | None]:
    root = repo_root or Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        dirty_out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return sha or None, bool(dirty_out.strip())
    except (OSError, subprocess.CalledProcessError):
        return None, None


def capture_local_manifest(
    *,
    environment_class: str | None = None,
    repo_root: Path | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a local/test manifest dict (no DB write)."""
    cls = environment_class or os.environ.get("IP_ENVIRONMENT_CLASS", "local")
    if cls not in {"local", "test", "staging", "production-demo"}:
        cls = "local"
    git_sha, git_dirty = _git_probe(repo_root)
    return {
        "environment_class": cls,
        "git_sha": git_sha or os.environ.get("GIT_SHA"),
        "git_dirty": git_dirty,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "compose_project": os.environ.get("COMPOSE_PROJECT_NAME"),
        "image_digests": {},
        "helm_chart_hash": None,
        "terraform_revision": None,
        "cloud_env_id": None,
        "extras": extras or {},
    }


def insert_environment_manifest(
    conn: Connection,
    *,
    fields: dict[str, Any] | None = None,
    commit: bool = False,
) -> UUID:
    data = fields or capture_local_manifest()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scenarios.environment_manifest (
                environment_class, git_sha, git_dirty, python_version, platform,
                compose_project, image_digests, helm_chart_hash,
                terraform_revision, cloud_env_id, extras
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s::jsonb, %s,
                %s, %s, %s::jsonb
            )
            RETURNING id
            """,
            (
                data.get("environment_class") or "local",
                data.get("git_sha"),
                data.get("git_dirty"),
                data.get("python_version"),
                data.get("platform"),
                data.get("compose_project"),
                Json(data.get("image_digests") or {}),
                data.get("helm_chart_hash"),
                data.get("terraform_revision"),
                data.get("cloud_env_id"),
                Json(data.get("extras") or {}),
            ),
        )
        mid = UUID(str(cur.fetchone()[0]))
    if commit:
        conn.commit()
    return mid


def get_environment_manifest(
    conn: Connection, *, manifest_id: UUID
) -> EnvironmentManifestView:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, environment_class, git_sha, git_dirty, python_version,
                   platform, compose_project, image_digests, helm_chart_hash,
                   terraform_revision, cloud_env_id, extras, captured_at
            FROM scenarios.environment_manifest
            WHERE id = %s
            """,
            (str(manifest_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise KeyError(f"unknown environment_manifest: {manifest_id}")
    return EnvironmentManifestView(
        id=UUID(str(row["id"])),
        environment_class=str(row["environment_class"]),
        git_sha=row.get("git_sha"),
        git_dirty=row.get("git_dirty"),
        python_version=row.get("python_version"),
        platform=row.get("platform"),
        compose_project=row.get("compose_project"),
        image_digests=dict(row.get("image_digests") or {}),
        helm_chart_hash=row.get("helm_chart_hash"),
        terraform_revision=row.get("terraform_revision"),
        cloud_env_id=row.get("cloud_env_id"),
        extras=dict(row.get("extras") or {}),
        captured_at=row.get("captured_at"),
    )
