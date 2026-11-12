"""GroundTruth access for the evaluator deployable only (N2)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row


def evaluator_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL_EVALUATOR",
        "postgresql://ip_evaluator:incidentpilot_evaluator@localhost:5432/incidentpilot",
    )


def app_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def runner_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL_RUNNER",
        "postgresql://ip_runner:incidentpilot_runner@localhost:5432/incidentpilot",
    )


@contextmanager
def get_evaluator_conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(evaluator_database_url()) as conn:
        yield conn


def get_ground_truth(
    conn: psycopg.Connection, *, scenario_key: str
) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, scenario_key, version, title,
                   origin_service_keys, expected_hypothesis_class,
                   expected_action_types, expected_severity,
                   match_spec, answer_payload, notes,
                   created_at, updated_at
            FROM eval.ground_truth
            WHERE scenario_key = %s
            """,
            (scenario_key,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def list_ground_truth(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT scenario_key, version, title,
                   origin_service_keys, expected_hypothesis_class,
                   expected_action_types, expected_severity
            FROM eval.ground_truth
            ORDER BY scenario_key
            """
        )
        return [dict(r) for r in cur.fetchall()]


def probe_select_denied(dsn: str) -> bool:
    """Return True if SELECT on eval.ground_truth is denied for this DSN."""
    try:
        with psycopg.connect(dsn, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM eval.ground_truth LIMIT 1")
                cur.fetchone()
        return False
    except psycopg.Error:
        return True
