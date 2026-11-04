"""Eval-only routes (C3). Ops RBAC alone cannot access GroundTruth."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from incidentpilot_api.db import get_eval_conn_with_entitlement

router = APIRouter(prefix="/eval", tags=["eval"])


class GroundTruthOut(BaseModel):
    id: UUID
    scenario_key: str
    answer_payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


@router.get("/ground-truth", response_model=list[GroundTruthOut])
def list_ground_truth(
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
    scenario_key: str | None = Query(default=None),
) -> list[GroundTruthOut]:
    """Read GroundTruth — requires eval entitlement (not ops Admin/Responder)."""
    sql = """
        SELECT id, scenario_key, answer_payload, created_at
        FROM eval.ground_truth
    """
    params: list[object] = []
    if scenario_key is not None:
        sql += " WHERE scenario_key = %s"
        params.append(scenario_key)
    sql += " ORDER BY created_at DESC LIMIT 100"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [GroundTruthOut(**row) for row in cur.fetchall()]
