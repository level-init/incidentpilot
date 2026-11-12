"""N3: ScenarioRun FAILED vs EVALUATED(+pass=false) are distinct."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "api",
    ROOT / "shared",
    ROOT / "scenario_runner",
    ROOT / "evaluator",
):
    sys.path.insert(0, str(p))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from incidentpilot_api.app import app  # noqa: E402
from incidentpilot_shared.scenario_lifecycle import (  # noqa: E402
    OUTCOME_INVALID,
    OUTCOME_SCORED_FAIL,
    OUTCOME_SCORED_PASS,
    IllegalScenarioTransition,
    get_scenario_run,
    mark_evaluated,
    outcome_for,
)

psycopg = pytest.importorskip("psycopg")


def _runner_dsn() -> str:
    return os.environ.get(
        "DATABASE_URL_RUNNER",
        "postgresql://ip_runner:incidentpilot_runner@localhost:5432/incidentpilot",
    )


def _eval_dsn() -> str:
    return os.environ.get(
        "DATABASE_URL_EVALUATOR",
        "postgresql://ip_evaluator:incidentpilot_evaluator@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_eval_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'scenarios'
                      AND table_name = 'scenario_run'
                      AND column_name = 'passed'
                    """
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def _insert_run(*, status: str) -> uuid.UUID:
    with psycopg.connect(_runner_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM scenarios.scenario WHERE key = 'bad_deploy'"
            )
            sid = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO scenarios.scenario_run (
                    scenario_id, status, injector_id, baseline_ok
                ) VALUES (%s, %s, 'bad_deploy', true)
                RETURNING id
                """,
                (str(sid), status),
            )
            run_id = uuid.UUID(str(cur.fetchone()[0]))
        conn.commit()
    return run_id


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_outcome_discrimination() -> None:
    assert outcome_for(status="FAILED", passed=None) == OUTCOME_INVALID
    assert outcome_for(status="EVALUATED", passed=True) == OUTCOME_SCORED_PASS
    assert outcome_for(status="EVALUATED", passed=False) == OUTCOME_SCORED_FAIL


def test_openapi_n3_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/eval/scenario-runs" in paths
    assert "/eval/scenario-runs/{run_id}" in paths
    assert "/eval/scenario-runs/{run_id}/evaluate" in paths
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "ScenarioRunOut" in schemas
    props = schemas["ScenarioRunOut"]["properties"]
    assert "outcome" in props
    assert "passed" in props


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0021 not reachable")
def test_evaluated_pass_false_distinct_from_failed(client: TestClient) -> None:
    failed_id = _insert_run(status="FAILED")
    # FAILED rows need failure_kind for realism; constraint allows null failure_kind
    with psycopg.connect(_runner_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE scenarios.scenario_run
                SET failure_kind = 'BASELINE',
                    failure_detail = 'dirty',
                    finished_at = now()
                WHERE id = %s
                """,
                (str(failed_id),),
            )
        conn.commit()

    scored_id = _insert_run(status="FAULT_INJECTED")
    with psycopg.connect(_eval_dsn()) as conn:
        view = mark_evaluated(
            conn,
            run_id=scored_id,
            passed=False,
            summary={"metrics": {"root_cause_match": 0.0}},
            commit=True,
        )
        assert view.status == "EVALUATED"
        assert view.passed is False
        assert view.outcome == OUTCOME_SCORED_FAIL

        failed_view = get_scenario_run(conn, run_id=failed_id)
        assert failed_view.status == "FAILED"
        assert failed_view.passed is None
        assert failed_view.outcome == OUTCOME_INVALID

        with pytest.raises(IllegalScenarioTransition):
            mark_evaluated(conn, run_id=failed_id, passed=False, commit=True)

    headers = {"Authorization": "Bearer local-dev-evaluator"}
    fail_res = client.get(f"/eval/scenario-runs/{failed_id}", headers=headers)
    assert fail_res.status_code == 200, fail_res.text
    fail_body = fail_res.json()
    assert fail_body["status"] == "FAILED"
    assert fail_body["passed"] is None
    assert fail_body["outcome"] == OUTCOME_INVALID

    score_res = client.get(f"/eval/scenario-runs/{scored_id}", headers=headers)
    assert score_res.status_code == 200, score_res.text
    score_body = score_res.json()
    assert score_body["status"] == "EVALUATED"
    assert score_body["passed"] is False
    assert score_body["outcome"] == OUTCOME_SCORED_FAIL
    # Distinct representations for UI later
    assert fail_body["outcome"] != score_body["outcome"]
    assert (fail_body["status"], fail_body["passed"]) != (
        score_body["status"],
        score_body["passed"],
    )


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0021 not reachable")
def test_evaluate_api_and_ops_denied(client: TestClient) -> None:
    run_id = _insert_run(status="FAULT_INJECTED")
    denied = client.post(
        f"/eval/scenario-runs/{run_id}/evaluate",
        headers={"Authorization": "Bearer local-dev"},
        json={"passed": True, "summary": {}},
    )
    assert denied.status_code == 403

    ok = client.post(
        f"/eval/scenario-runs/{run_id}/evaluate",
        headers={"Authorization": "Bearer local-dev-evaluator"},
        json={"passed": True, "summary": {"note": "harness"}},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "EVALUATED"
    assert body["passed"] is True
    assert body["outcome"] == OUTCOME_SCORED_PASS
