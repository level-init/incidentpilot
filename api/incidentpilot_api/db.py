"""Postgres connection helper for the API."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def get_conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url()) as conn:
        yield conn
