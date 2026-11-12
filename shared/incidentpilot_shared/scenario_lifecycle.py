"""ScenarioRun lifecycle (N3) — FAILED ≠ EVALUATED(pass=false).

Shared by evaluator + eval HTTP APIs (api must not import evaluator package).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

ScenarioRunStatus = Literal[
    "PENDING",
    "BASELINE_PASSED",
    "FAULT_INJECTED",
    "FAILED",
    "EVALUATED",
]

# Terminal-ish outcomes for API/UI discrimination.
OUTCOME_INVALID = "INVALID_RUN"  # status=FAILED — do not score as IP miss
OUTCOME_SCORED_PASS = "SCORED_PASS"  # EVALUATED + passed=true
OUTCOME_SCORED_FAIL = "SCORED_FAIL"  # EVALUATED + passed=false
OUTCOME_IN_PROGRESS = "IN_PROGRESS"


class IllegalScenarioTransition(Exception):
    """Raised when a ScenarioRun status transition is not allowed."""


@dataclass(frozen=True)
class ScenarioRunView:
    id: UUID
    scenario_key: str
    status: str
    passed: bool | None
    failure_kind: str | None
    failure_detail: str | None
    baseline_ok: bool | None
    evaluation_summary: dict[str, Any]
    outcome: str
    started_at: Any
    finished_at: Any
    evaluated_at: Any
    reset_at: Any
    injector_id: str | None
    environment_manifest_id: UUID | None = None
    environment_manifest: dict[str, Any] | None = None


def outcome_for(*, status: str, passed: bool | None) -> str:
    if status == "FAILED":
        return OUTCOME_INVALID
    if status == "EVALUATED":
        if passed is True:
            return OUTCOME_SCORED_PASS
        if passed is False:
            return OUTCOME_SCORED_FAIL
        raise ValueError("EVALUATED requires passed true|false")
    return OUTCOME_IN_PROGRESS


def _load_manifest_dict(
    conn: Connection, manifest_id: UUID | None
) -> dict[str, Any] | None:
    if manifest_id is None:
        return None
    from incidentpilot_shared.environment_manifest import get_environment_manifest

    m = get_environment_manifest(conn, manifest_id=manifest_id)
    return {
        "id": str(m.id),
        "environment_class": m.environment_class,
        "git_sha": m.git_sha,
        "git_dirty": m.git_dirty,
        "python_version": m.python_version,
        "platform": m.platform,
        "compose_project": m.compose_project,
        "image_digests": m.image_digests,
        "helm_chart_hash": m.helm_chart_hash,
        "terraform_revision": m.terraform_revision,
        "cloud_env_id": m.cloud_env_id,
        "extras": m.extras,
        "captured_at": m.captured_at,
    }


def _row_to_view(
    row: dict[str, Any], *, manifest: dict[str, Any] | None = None
) -> ScenarioRunView:
    passed = row.get("passed")
    status = str(row["status"])
    mid_raw = row.get("environment_manifest_id")
    mid = UUID(str(mid_raw)) if mid_raw is not None else None
    return ScenarioRunView(
        id=UUID(str(row["id"])),
        scenario_key=str(row["scenario_key"]),
        status=status,
        passed=passed,
        failure_kind=row.get("failure_kind"),
        failure_detail=row.get("failure_detail"),
        baseline_ok=row.get("baseline_ok"),
        evaluation_summary=dict(row.get("evaluation_summary") or {}),
        outcome=outcome_for(status=status, passed=passed),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        evaluated_at=row.get("evaluated_at"),
        reset_at=row.get("reset_at"),
        injector_id=row.get("injector_id"),
        environment_manifest_id=mid,
        environment_manifest=manifest,
    )


def get_scenario_run(conn: Connection, *, run_id: UUID) -> ScenarioRunView:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT r.id, r.status, r.passed, r.failure_kind, r.failure_detail,
                   r.baseline_ok, r.evaluation_summary, r.injector_id,
                   r.environment_manifest_id,
                   r.started_at, r.finished_at, r.evaluated_at, r.reset_at,
                   s.key AS scenario_key
            FROM scenarios.scenario_run r
            JOIN scenarios.scenario s ON s.id = r.scenario_id
            WHERE r.id = %s
            """,
            (str(run_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise KeyError(f"unknown scenario_run: {run_id}")
    data = dict(row)
    mid_raw = data.get("environment_manifest_id")
    mid = UUID(str(mid_raw)) if mid_raw is not None else None
    return _row_to_view(data, manifest=_load_manifest_dict(conn, mid))


def list_scenario_runs(
    conn: Connection,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[ScenarioRunView]:
    sql = """
        SELECT r.id, r.status, r.passed, r.failure_kind, r.failure_detail,
               r.baseline_ok, r.evaluation_summary, r.injector_id,
               r.environment_manifest_id,
               r.started_at, r.finished_at, r.evaluated_at, r.reset_at,
               s.key AS scenario_key
        FROM scenarios.scenario_run r
        JOIN scenarios.scenario s ON s.id = r.scenario_id
    """
    params: list[object] = []
    if status is not None:
        sql += " WHERE r.status = %s"
        params.append(status)
    sql += " ORDER BY r.started_at DESC LIMIT %s"
    params.append(limit)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        # List omits nested manifest payload for brevity; id is present.
        return [_row_to_view(dict(r)) for r in cur.fetchall()]


def mark_evaluated(
    conn: Connection,
    *,
    run_id: UUID,
    passed: bool,
    summary: dict[str, Any] | None = None,
    commit: bool = True,
) -> ScenarioRunView:
    """Pin EVALUATED. Only from FAULT_INJECTED. Never from FAILED."""
    summary = summary or {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT status, passed FROM scenarios.scenario_run WHERE id = %s",
            (str(run_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(f"unknown scenario_run: {run_id}")
        current = str(row["status"])
        if current == "FAILED":
            raise IllegalScenarioTransition(
                "cannot EVALUATE a FAILED run (invalid baseline/infra — not a scored miss)"
            )
        if current == "EVALUATED":
            # Idempotent re-read; N6 will pin immutable eval ids later.
            return get_scenario_run(conn, run_id=run_id)
        if current != "FAULT_INJECTED":
            raise IllegalScenarioTransition(
                f"EVALUATED requires FAULT_INJECTED, got {current}"
            )

        cur.execute(
            """
            UPDATE scenarios.scenario_run
            SET status = 'EVALUATED',
                passed = %s,
                evaluation_summary = %s::jsonb,
                evaluated_at = now(),
                finished_at = COALESCE(finished_at, now())
            WHERE id = %s AND status = 'FAULT_INJECTED'
            """,
            (passed, Json(summary), str(run_id)),
        )
        if cur.rowcount != 1:
            raise IllegalScenarioTransition(
                f"concurrent update lost for scenario_run {run_id}"
            )
    if commit:
        conn.commit()
    return get_scenario_run(conn, run_id=run_id)
