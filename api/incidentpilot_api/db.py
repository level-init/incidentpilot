"""Postgres connection helpers for the API."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def evaluator_database_url() -> str:
    """Evaluator DB role — may read eval.ground_truth; ops app role must not."""
    return os.environ.get(
        "DATABASE_URL_EVALUATOR",
        "postgresql://ip_evaluator:incidentpilot_evaluator@localhost:5432/incidentpilot",
    )


def get_conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url()) as conn:
        yield conn


def get_eval_conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(evaluator_database_url()) as conn:
        yield conn
