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
from incidentpilot_shared.operational_evaluation import (
    OperationalEvalError,
    OperationalEvaluationView,
    get_operational_evaluation,
    get_operational_evaluation_for_run,
    pin_operational_evaluation,
)
from incidentpilot_shared.postmortem_evaluation import (
    PostmortemEvalError,
    PostmortemEvaluationView,
    get_postmortem_evaluation,
    get_postmortem_evaluation_for_run,
    list_evaluation_family,
    pin_postmortem_evaluation,
)
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


class OperationalPinBody(BaseModel):
    incident_id: UUID
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class OperationalEvaluationOut(BaseModel):
    id: UUID
    scenario_run_id: UUID
    incident_id: UUID
    pinned_incident_revision: int
    environment_manifest_id: UUID | None = None
    ground_truth_id: UUID | None = None
    ground_truth_version: int | None = None
    scenario_key: str
    passed: bool
    score: float | None = None
    hard_fail: bool = False
    threshold: float
    metrics_payload: list[dict[str, object]] = Field(default_factory=list)
    summary: dict[str, object] = Field(default_factory=dict)
    metric_engine_version: str
    created_at: datetime | None = None
    idempotent_hit: bool = False


def _operational_out(view: OperationalEvaluationView) -> OperationalEvaluationOut:
    return OperationalEvaluationOut(
        id=view.id,
        scenario_run_id=view.scenario_run_id,
        incident_id=view.incident_id,
        pinned_incident_revision=view.pinned_incident_revision,
        environment_manifest_id=view.environment_manifest_id,
        ground_truth_id=view.ground_truth_id,
        ground_truth_version=view.ground_truth_version,
        scenario_key=view.scenario_key,
        passed=view.passed,
        score=view.score,
        hard_fail=view.hard_fail,
        threshold=view.threshold,
        metrics_payload=list(view.metrics_payload),
        summary=dict(view.summary),
        metric_engine_version=view.metric_engine_version,
        created_at=view.created_at,
        idempotent_hit=view.idempotent_hit,
    )


class PostmortemPinBody(BaseModel):
    incident_id: UUID
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class PostmortemEvaluationOut(BaseModel):
    id: UUID
    scenario_run_id: UUID
    operational_evaluation_id: UUID
    incident_id: UUID
    postmortem_id: UUID
    pinned_incident_revision: int
    environment_manifest_id: UUID | None = None
    ground_truth_id: UUID | None = None
    scenario_key: str
    passed: bool
    score: float | None = None
    hard_fail: bool = False
    threshold: float
    metrics_payload: list[dict[str, object]] = Field(default_factory=list)
    summary: dict[str, object] = Field(default_factory=dict)
    metric_engine_version: str
    created_at: datetime | None = None
    idempotent_hit: bool = False


class EvaluationFamilyOut(BaseModel):
    scenario_run_id: str
    operational_evaluation: dict[str, object] | None = None
    postmortem_evaluation: dict[str, object] | None = None
    count: int


def _postmortem_out(view: PostmortemEvaluationView) -> PostmortemEvaluationOut:
    return PostmortemEvaluationOut(
        id=view.id,
        scenario_run_id=view.scenario_run_id,
        operational_evaluation_id=view.operational_evaluation_id,
        incident_id=view.incident_id,
        postmortem_id=view.postmortem_id,
        pinned_incident_revision=view.pinned_incident_revision,
        environment_manifest_id=view.environment_manifest_id,
        ground_truth_id=view.ground_truth_id,
        scenario_key=view.scenario_key,
        passed=view.passed,
        score=view.score,
        hard_fail=view.hard_fail,
        threshold=view.threshold,
        metrics_payload=list(view.metrics_payload),
        summary=dict(view.summary),
        metric_engine_version=view.metric_engine_version,
        created_at=view.created_at,
        idempotent_hit=view.idempotent_hit,
    )


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


@router.post(
    "/scenario-runs/{run_id}/operational-evaluation",
    response_model=OperationalEvaluationOut,
)
def pin_operational_evaluation_route(
    run_id: UUID,
    body: OperationalPinBody,
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
) -> OperationalEvaluationOut:
    """N6: pin immutable operational score at RESOLVED (idempotent)."""
    try:
        view = pin_operational_evaluation(
            conn,
            scenario_run_id=run_id,
            incident_id=body.incident_id,
            threshold=body.threshold,
            commit=True,
        )
    except OperationalEvalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _operational_out(view)


@router.get(
    "/scenario-runs/{run_id}/operational-evaluation",
    response_model=OperationalEvaluationOut,
)
def get_operational_evaluation_for_run_route(
    run_id: UUID,
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
) -> OperationalEvaluationOut:
    view = get_operational_evaluation_for_run(conn, scenario_run_id=run_id)
    if view is None:
        raise HTTPException(status_code=404, detail="operational evaluation not found")
    return _operational_out(view)


@router.get(
    "/operational-evaluations/{evaluation_id}",
    response_model=OperationalEvaluationOut,
)
def get_operational_evaluation_route(
    evaluation_id: UUID,
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
) -> OperationalEvaluationOut:
    try:
        return _operational_out(
            get_operational_evaluation(conn, evaluation_id=evaluation_id)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/scenario-runs/{run_id}/postmortem-evaluation",
    response_model=PostmortemEvaluationOut,
)
def pin_postmortem_evaluation_route(
    run_id: UUID,
    body: PostmortemPinBody,
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
) -> PostmortemEvaluationOut:
    """N7: pin immutable postmortem score at CLOSED (requires operational pin)."""
    try:
        view = pin_postmortem_evaluation(
            conn,
            scenario_run_id=run_id,
            incident_id=body.incident_id,
            threshold=body.threshold,
            commit=True,
        )
    except PostmortemEvalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _postmortem_out(view)


@router.get(
    "/scenario-runs/{run_id}/postmortem-evaluation",
    response_model=PostmortemEvaluationOut,
)
def get_postmortem_evaluation_for_run_route(
    run_id: UUID,
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
) -> PostmortemEvaluationOut:
    view = get_postmortem_evaluation_for_run(conn, scenario_run_id=run_id)
    if view is None:
        raise HTTPException(status_code=404, detail="postmortem evaluation not found")
    return _postmortem_out(view)


@router.get(
    "/postmortem-evaluations/{evaluation_id}",
    response_model=PostmortemEvaluationOut,
)
def get_postmortem_evaluation_route(
    evaluation_id: UUID,
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
) -> PostmortemEvaluationOut:
    try:
        return _postmortem_out(
            get_postmortem_evaluation(conn, evaluation_id=evaluation_id)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/scenario-runs/{run_id}/evaluation-family",
    response_model=EvaluationFamilyOut,
)
def get_evaluation_family_route(
    run_id: UUID,
    conn: Annotated[Connection, Depends(get_eval_conn_with_entitlement)],
) -> EvaluationFamilyOut:
    """N7 AC: both EvaluationResults for a scored run family."""
    family = list_evaluation_family(conn, scenario_run_id=run_id)
    return EvaluationFamilyOut(**family)


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
