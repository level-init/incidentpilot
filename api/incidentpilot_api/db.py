"""Postgres connection helpers for the API."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Annotated

import psycopg
from fastapi import Depends

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.rbac import Permission, require_eval_entitlement, require_permission


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


def get_conn_with_permission(
    permission: Permission,
) -> Callable[..., Iterator[psycopg.Connection]]:
    """Open DB only after RBAC passes — denial paths must not require Postgres."""

    def _dep(
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> Iterator[psycopg.Connection]:
        require_permission(principal, permission)
        with psycopg.connect(database_url()) as conn:
            yield conn

    return _dep


def get_eval_conn_with_entitlement(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Iterator[psycopg.Connection]:
    """Open evaluator DB only after eval entitlement passes."""
    require_eval_entitlement(principal)
    with psycopg.connect(evaluator_database_url()) as conn:
        yield conn
