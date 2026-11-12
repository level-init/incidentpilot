"""Eval-only routes (C3) + Approval harness (I6).

GroundTruth requires eval entitlement. The approval harness also requires
eval entitlement and writes **real** ``domain.approval`` decisions (no Slack).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.db import get_conn, get_eval_conn_with_entitlement
from incidentpilot_api.rbac import (
    assert_approval_allowed_by_policy,
    require_eval_entitlement,
)
from incidentpilot_api.schemas import ApprovalOut
from incidentpilot_api.temporal import get_temporal_client
from incidentpilot_shared.approval_harness import harness_decide_approval
from incidentpilot_shared.scenario_lifecycle import (
    IllegalScenarioTransition,
    ScenarioRunView,
    get_scenario_run,
    list_scenario_runs,
    mark_evaluated,
)

router = APIRouter(prefix="/eval", tags=["eval"])


class GroundTruthOut(BaseModel):
    id: UUID
    scenario_key: str
    version: int = 1
    title: str = ""
    origin_service_keys: list[str] = Field(default_factory=list)
    expected_hypothesis_class: str | None = None
    expected_action_types: list[str] = Field(default_factory=list)
    expected_severity: str | None = None
    match_spec: dict[str, object] = Field(default_factory=dict)
    answer_payload: dict[str, object] = Field(default_factory=dict)
    notes: str = ""
    created_at: datetime
    updated_at: datetime | None = None


class HarnessDecideBody(BaseModel):
    status: str = Field(description="APPROVED or REJECTED")


class HarnessDecideOut(BaseModel):
    approval: ApprovalOut
    incident_id: UUID
    action_status: str
    decided_by: str
    noop: bool
    workflow_signaled: bool
    signal_error: str | None = None


class EnvironmentManifestOut(BaseModel):
    """N4: pinned local/test execution identity (cloud fields optional / O10)."""

    id: str
    environment_class: str
    git_sha: str | None = None
    git_dirty: bool | None = None
    python_version: str | None = None
    platform: str | None = None
    compose_project: str | None = None
    image_digests: dict[str, object] = Field(default_factory=dict)
    helm_chart_hash: str | None = None
    terraform_revision: str | None = None
    cloud_env_id: str | None = None
    extras: dict[str, object] = Field(default_factory=dict)
    captured_at: datetime | None = None


class ScenarioRunOut(BaseModel):
    """N3/N4: FAILED vs EVALUATED+passed=false; pinned environment_manifest."""

    id: UUID
    scenario_key: str
    status: str
    passed: bool | None = None
    outcome: str
    failure_kind: str | None = None
    failure_detail: str | None = None
    baseline_ok: bool | None = None
    evaluation_summary: dict[str, object] = Field(default_factory=dict)
    injector_id: str | None = None
    environment_manifest_id: UUID | None = None
    environment_manifest: EnvironmentManifestOut | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    evaluated_at: datetime | None = None
    reset_at: datetime | None = None


class ScenarioRunEvaluateBody(BaseModel):
    passed: bool
    summary: dict[str, object] = Field(default_factory=dict)


def _scenario_run_out(view: ScenarioRunView) -> ScenarioRunOut:
    manifest_out: EnvironmentManifestOut | None = None
    if view.environment_manifest:
        m = dict(view.environment_manifest)
        captured = m.get("captured_at")
        manifest_out = EnvironmentManifestOut(
            id=str(m.get("id") or ""),
            environment_class=str(m.get("environment_class") or "local"),
            git_sha=m.get("git_sha"),
            git_dirty=m.get("git_dirty"),
            python_version=m.get("python_version"),
            platform=m.get("platform"),
            compose_project=m.get("compose_project"),
            image_digests=dict(m.get("image_digests") or {}),
            helm_chart_hash=m.get("helm_chart_hash"),
            terraform_revision=m.get("terraform_revision"),
            cloud_env_id=m.get("cloud_env_id"),
            extras=dict(m.get("extras") or {}),
            captured_at=captured,
        )
    return ScenarioRunOut(
        id=view.id,
        scenario_key=view.scenario_key,
        status=view.status,
        passed=view.passed,
        outcome=view.outcome,
        failure_kind=view.failure_kind,
        failure_detail=view.failure_detail,
        baseline_ok=view.baseline_ok,
        evaluation_summary=dict(view.evaluation_summary or {}),
        injector_id=view.injector_id,
        environment_manifest_id=view.environment_manifest_id,
        environment_manifest=manifest_out,
        started_at=view.started_at,
        finished_at=view.finished_at,
        evaluated_at=view.evaluated_at,
        reset_at=view.reset_at,
    )


@router.get("/scenario-runs", response_model=list[ScenarioRunOut])
def list_eval_scenario_runs(
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ScenarioRunOut]:
    """List ScenarioRuns — eval entitlement. Distinguishes FAILED vs EVALUATED."""
    return [
        _scenario_run_out(v)
        for v in list_scenario_runs(conn, status=status_filter, limit=limit)
    ]


@router.get("/scenario-runs/{run_id}", response_model=ScenarioRunOut)
def get_eval_scenario_run(
    run_id: UUID,
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
) -> ScenarioRunOut:
    try:
        return _scenario_run_out(get_scenario_run(conn, run_id=run_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/scenario-runs/{run_id}/evaluate",
    response_model=ScenarioRunOut,
)
def evaluate_scenario_run(
    run_id: UUID,
    body: ScenarioRunEvaluateBody,
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
) -> ScenarioRunOut:
    """Harness/score pin: FAULT_INJECTED → EVALUATED (passed true|false).

    Refuses FAILED runs — invalid baseline is not a scored miss.
    """
    try:
        view = mark_evaluated(
            conn,
            run_id=run_id,
            passed=body.passed,
            summary=dict(body.summary),
            commit=True,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IllegalScenarioTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _scenario_run_out(view)


@router.get("/ground-truth", response_model=list[GroundTruthOut])
def list_ground_truth(
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
    scenario_key: str | None = Query(default=None),
) -> list[GroundTruthOut]:
    """Read GroundTruth — requires eval entitlement (not ops Admin/Responder)."""
    sql = """
        SELECT id, scenario_key, version, title,
               origin_service_keys, expected_hypothesis_class,
               expected_action_types, expected_severity,
               match_spec, answer_payload, notes,
               created_at, updated_at
        FROM eval.ground_truth
    """
    params: list[object] = []
    if scenario_key is not None:
        sql += " WHERE scenario_key = %s"
        params.append(scenario_key)
    sql += " ORDER BY created_at DESC LIMIT 100"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = []
        for row in cur.fetchall():
            data = dict(row)
            data["origin_service_keys"] = list(data.get("origin_service_keys") or [])
            data["expected_action_types"] = list(
                data.get("expected_action_types") or []
            )
            rows.append(GroundTruthOut(**data))
        return rows


@router.post(
    "/approvals/{approval_id}/decide",
    response_model=HarnessDecideOut,
)
async def harness_decide_approval_route(
    approval_id: UUID,
    body: HarnessDecideBody,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> HarnessDecideOut:
    """I6 eval/test harness — real ApprovalDecision + workflow signal.

    Requires ``eval_entitled`` (ops Responder alone is not enough). Uses the
    domain decide command (same rows as human decide) and signals
    ``approval_decision`` so ``wait_for_approval`` resumes.
    """
    require_eval_entitlement(principal)
    if body.status not in {"APPROVED", "REJECTED"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must be APPROVED or REJECTED",
        )

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT a.status AS approval_status, pd.decision AS policy_decision
            FROM domain.approval a
            LEFT JOIN domain.policy_decision pd
              ON pd.action_id = a.action_id
             AND pd.action_version = a.action_version
            WHERE a.id = %s
            """,
            (str(approval_id),),
        )
        gate = cur.fetchone()
    if gate is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if gate["approval_status"] != "PENDING" and gate["approval_status"] != body.status:
        raise HTTPException(status_code=409, detail="approval is not PENDING")
    assert_approval_allowed_by_policy(
        None if gate["policy_decision"] is None else str(gate["policy_decision"])
    )

    try:
        client = await get_temporal_client()
    except Exception:  # noqa: BLE001 — harness still records domain decision
        client = None

    try:
        result = await harness_decide_approval(
            conn,
            approval_id=approval_id,
            status=body.status,
            decided_by=principal.actor_id,
            temporal_client=client,
            commit=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, action_id, action_version, status, decided_by
            FROM domain.approval WHERE id = %s
            """,
            (str(result.approval_id),),
        )
        out = cur.fetchone()
    assert out is not None
    return HarnessDecideOut(
        approval=ApprovalOut(**out),
        incident_id=result.incident_id,
        action_status=result.action_status,
        decided_by=result.decided_by,
        noop=result.noop,
        workflow_signaled=result.workflow_signaled,
        signal_error=result.signal_error,
    )
