"""Postgres helpers for scenario-runner (ip_runner role — never eval)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def runner_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL_RUNNER",
        "postgresql://ip_runner:incidentpilot_runner@localhost:5432/incidentpilot",
    )


@contextmanager
def get_runner_conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(runner_database_url()) as conn:
        yield conn


def assert_ground_truth_denied(conn: psycopg.Connection) -> None:
    """AC: runner cannot SELECT GT — raises on unexpected allow."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM eval.ground_truth LIMIT 1")
            cur.fetchone()
    except psycopg.Error:
        conn.rollback()
        return
    raise RuntimeError("ip_runner unexpectedly allowed SELECT on eval.ground_truth")


def get_scenario_by_key(conn: psycopg.Connection, key: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, key, title, description, injector_id, autonomy_level, enabled
            FROM scenarios.scenario
            WHERE key = %s
            """,
            (key,),
        )
        row = cur.fetchone()
    if row is None:
        raise KeyError(f"unknown scenario key: {key}")
    return dict(row)


def list_scenarios(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT key, title, injector_id, autonomy_level, enabled
            FROM scenarios.scenario
            ORDER BY key
            """
        )
        return [dict(r) for r in cur.fetchall()]


def create_scenario_run(
    conn: psycopg.Connection,
    *,
    scenario_id: UUID,
    injector_id: str,
    environment_manifest_id: UUID | None = None,
) -> UUID:
    """Create a ScenarioRun. Pins environment_manifest (N4) when not provided."""
    from incidentpilot_shared.environment_manifest import (
        capture_local_manifest,
        insert_environment_manifest,
    )

    mid = environment_manifest_id
    if mid is None:
        mid = insert_environment_manifest(
            conn, fields=capture_local_manifest(), commit=False
        )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scenarios.scenario_run (
                scenario_id, status, injector_id, environment_manifest_id
            ) VALUES (%s, 'PENDING', %s, %s)
            RETURNING id
            """,
            (str(scenario_id), injector_id, str(mid)),
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return UUID(str(run_id))


def mark_baseline_passed(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
    baseline_payload: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scenarios.scenario_run
            SET status = 'BASELINE_PASSED',
                baseline_ok = true,
                baseline_payload = %s
            WHERE id = %s AND status = 'PENDING'
            """,
            (Json(baseline_payload), str(run_id)),
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"cannot mark baseline passed for run {run_id}")
    conn.commit()


def mark_fault_injected(conn: psycopg.Connection, *, run_id: UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scenarios.scenario_run
            SET status = 'FAULT_INJECTED'
            WHERE id = %s AND status = 'BASELINE_PASSED'
            """,
            (str(run_id),),
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"cannot mark fault injected for run {run_id}")
    conn.commit()


def mark_failed(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
    failure_kind: str,
    failure_detail: str,
    baseline_ok: bool | None = False,
    baseline_payload: dict[str, Any] | None = None,
) -> None:
    payload = baseline_payload if baseline_payload is not None else {}
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scenarios.scenario_run
            SET status = 'FAILED',
                failure_kind = %s,
                failure_detail = %s,
                baseline_ok = %s,
                baseline_payload = %s::jsonb,
                finished_at = now()
            WHERE id = %s AND status IN ('PENDING', 'BASELINE_PASSED')
            """,
            (
                failure_kind,
                failure_detail[:2000],
                baseline_ok,
                Json(payload),
                str(run_id),
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"cannot mark failed for run {run_id}")
    conn.commit()


def mark_reset(conn: psycopg.Connection, *, run_id: UUID | None = None) -> int:
    """Stamp reset_at on open/active runs. Never deletes history."""
    with conn.cursor() as cur:
        if run_id is not None:
            cur.execute(
                """
                UPDATE scenarios.scenario_run
                SET reset_at = now()
                WHERE id = %s AND reset_at IS NULL
                """,
                (str(run_id),),
            )
        else:
            cur.execute(
                """
                UPDATE scenarios.scenario_run
                SET reset_at = now()
                WHERE reset_at IS NULL
                  AND status IN ('FAULT_INJECTED', 'FAILED', 'BASELINE_PASSED')
                """
            )
        n = cur.rowcount
    conn.commit()
    return int(n)


def get_scenario_run(conn: psycopg.Connection, run_id: UUID) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT r.id, r.status, r.passed, r.failure_kind, r.failure_detail,
                   r.baseline_ok, r.baseline_payload, r.injector_id,
                   r.evaluation_summary, r.environment_manifest_id,
                   r.started_at, r.finished_at,
                   r.evaluated_at, r.reset_at,
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
    return dict(row)
