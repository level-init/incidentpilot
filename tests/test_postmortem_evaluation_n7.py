"""N7: PostmortemEvaluation pin at CLOSED — links OperationalEvaluation."""

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
from incidentpilot_scenario_runner.baseline import BaselineGateResult  # noqa: E402
from incidentpilot_scenario_runner.db import get_runner_conn, mark_fault_injected  # noqa: E402
from incidentpilot_scenario_runner.runner import run_scenario  # noqa: E402
from incidentpilot_shared.eval_metrics.postmortem import (  # noqa: E402
    PostmortemScoreInput,
    evaluate_postmortem,
)
from incidentpilot_shared.operational_evaluation import (  # noqa: E402
    pin_operational_evaluation,
)
from incidentpilot_shared.postmortem_evaluation import (  # noqa: E402
    list_evaluation_family,
    pin_postmortem_evaluation,
)

psycopg = pytest.importorskip("psycopg")


def _app_dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
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
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'eval'
                      AND table_name = 'postmortem_evaluation'
                    """
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_postmortem_metrics_hard_fail_without_final() -> None:
    result = evaluate_postmortem(
        PostmortemScoreInput(
            postmortem_status="DRAFT",
            corrective_actions_count=0,
        )
    )
    assert result.hard_fail is True
    assert result.passed is False


def test_postmortem_metrics_pass() -> None:
    result = evaluate_postmortem(
        PostmortemScoreInput(
            postmortem_status="FINAL",
            corrective_actions_count=1,
            known_evidence_ids=frozenset({"EV-1"}),
            cited_evidence_ids=frozenset({"EV-1"}),
        )
    )
    assert result.hard_fail is False
    assert result.passed is True


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0024 not reachable")
def test_two_evaluation_results_per_run_family(client: TestClient) -> None:
    # Operational pin requires RESOLVED — create RESOLVED, pin, then CLOSE + postmortem pin.
    outcome = run_scenario(
        "bad_deploy",
        baseline_fn=lambda: BaselineGateResult(ok=True, payload={}, detail="ok"),
        inject=False,
    )
    with get_runner_conn() as conn:
        mark_fault_injected(conn, run_id=outcome.run_id)

    with psycopg.connect(_app_dsn()) as conn:
        with conn.cursor() as cur:
            public_id = f"INC-N7F-{uuid.uuid4().hex[:8]}"
            cur.execute(
                """
                INSERT INTO domain.incident (
                    public_id, state, title, severity, incident_revision
                ) VALUES (%s, 'RESOLVED', 'n7 family', 'SEV2', 4)
                RETURNING id
                """,
                (public_id,),
            )
            iid = uuid.UUID(str(cur.fetchone()[0]))
            cur.execute(
                """
                INSERT INTO domain.service (key, display_name, environment)
                VALUES ('payment', 'Payment', 'local')
                ON CONFLICT (key, environment) DO UPDATE
                    SET display_name = EXCLUDED.display_name
                RETURNING id
                """
            )
            sid = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO domain.incident_service (incident_id, service_id)
                VALUES (%s, %s) ON CONFLICT DO NOTHING
                """,
                (str(iid), str(sid)),
            )
            cur.execute(
                """
                INSERT INTO domain.hypothesis (
                    incident_id, status, statement, hypothesis_class,
                    proposed_by, cited_evidence_ids
                ) VALUES (
                    %s, 'CONFIRMED', 'bad deploy', 'bad_deployment',
                    'test', '{}'::uuid[]
                )
                """,
                (str(iid),),
            )
            cur.execute(
                """
                INSERT INTO domain.action (
                    incident_id, action_type, status, is_reversible, proposed_by
                ) VALUES (%s, 'ROLLBACK_DEPLOYMENT', 'SUCCEEDED', true, 'test')
                """,
                (str(iid),),
            )
        conn.commit()

    with psycopg.connect(_eval_dsn()) as conn:
        ops = pin_operational_evaluation(
            conn,
            scenario_run_id=outcome.run_id,
            incident_id=iid,
            commit=True,
        )

    with psycopg.connect(_app_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO domain.postmortem (
                    incident_id, status, title, body_markdown, corrective_actions,
                    cited_evidence_ids, author, provenance, finalized_at
                ) VALUES (
                    %s, 'FINAL', 'n7 pm', 'done',
                    '[{"title":"Canary"}]'::jsonb,
                    '{}'::uuid[], 'test', '{"claims":[]}'::jsonb, now()
                )
                """,
                (str(iid),),
            )
            cur.execute(
                """
                UPDATE domain.incident
                SET state = 'CLOSED', incident_revision = incident_revision + 1
                WHERE id = %s
                """,
                (str(iid),),
            )
        conn.commit()

    with psycopg.connect(_eval_dsn()) as conn:
        pm = pin_postmortem_evaluation(
            conn,
            scenario_run_id=outcome.run_id,
            incident_id=iid,
            commit=True,
        )
        assert pm.operational_evaluation_id == ops.id
        assert pm.environment_manifest_id == ops.environment_manifest_id

        again = pin_postmortem_evaluation(
            conn,
            scenario_run_id=outcome.run_id,
            incident_id=iid,
            commit=True,
        )
        assert again.id == pm.id
        assert again.idempotent_hit is True

        family = list_evaluation_family(conn, scenario_run_id=outcome.run_id)
        assert family["count"] == 2
        assert family["operational_evaluation"]["id"] == str(ops.id)
        assert family["postmortem_evaluation"]["id"] == str(pm.id)
        assert (
            family["operational_evaluation"]["environment_manifest_id"]
            == family["postmortem_evaluation"]["environment_manifest_id"]
        )

        denied = False
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE eval.postmortem_evaluation
                    SET passed = NOT passed WHERE id = %s
                    """,
                    (str(pm.id),),
                )
            conn.commit()
        except psycopg.Error:
            conn.rollback()
            denied = True
        assert denied

    headers = {"Authorization": "Bearer local-dev-evaluator"}
    fam = client.get(
        f"/eval/scenario-runs/{outcome.run_id}/evaluation-family",
        headers=headers,
    )
    assert fam.status_code == 200, fam.text
    body = fam.json()
    assert body["count"] == 2


def test_openapi_n7_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/eval/scenario-runs/{run_id}/postmortem-evaluation" in paths
    assert "/eval/scenario-runs/{run_id}/evaluation-family" in paths
    assert "/eval/postmortem-evaluations/{evaluation_id}" in paths
