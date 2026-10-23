"""Postgres access for Temporal activities (ip_app role)."""

from __future__ import annotations

import os

import psycopg


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url())
