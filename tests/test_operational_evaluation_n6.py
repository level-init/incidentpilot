"""N6: OperationalEvaluation pin at RESOLVED — immutable + idempotent."""

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
from incidentpilot_scenario_runner.db import (  # noqa: E402
    get_runner_conn,
    mark_fault_injected,
)
from incidentpilot_scenario_runner.runner import run_scenario  # noqa: E402
from incidentpilot_shared.operational_evaluation import (  # noqa: E402
    pin_operational_evaluation,
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
                      AND table_name = 'operational_evaluation'
                    """
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _make_resolved_incident(*, service_key: str = "payment") -> tuple[uuid.UUID, int]:
    with psycopg.connect(_app_dsn()) as conn:
        with conn.cursor() as cur:
            public_id = f"INC-N6-{uuid.uuid4().hex[:8]}"
            cur.execute(
                """
                INSERT INTO domain.incident (
                    public_id, state, title, severity, incident_revision
                ) VALUES (%s, 'RESOLVED', 'n6 pin', 'SEV2', 3)
                RETURNING id, incident_revision
                """,
                (public_id,),
            )
            iid, rev = cur.fetchone()
            cur.execute(
                """
                INSERT INTO domain.service (key, display_name, environment)
                VALUES (%s, %s, 'local')
                ON CONFLICT (key, environment) DO UPDATE
                    SET display_name = EXCLUDED.display_name
                RETURNING id
                """,
                (service_key, service_key),
            )
            sid = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO domain.incident_service (incident_id, service_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
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
    return uuid.UUID(str(iid)), int(rev)


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0023 not reachable")
def test_pin_immutable_and_idempotent(client: TestClient) -> None:
    outcome = run_scenario(
        "bad_deploy",
        baseline_fn=lambda: BaselineGateResult(ok=True, payload={}, detail="ok"),
        inject=False,
    )
    with get_runner_conn() as conn:
        mark_fault_injected(conn, run_id=outcome.run_id)

    incident_id, rev = _make_resolved_incident()

    with psycopg.connect(_eval_dsn()) as conn:
        first = pin_operational_evaluation(
            conn,
            scenario_run_id=outcome.run_id,
            incident_id=incident_id,
            commit=True,
        )
        assert first.pinned_incident_revision == rev
        assert first.idempotent_hit is False
        first_id = first.id

        second = pin_operational_evaluation(
            conn,
            scenario_run_id=outcome.run_id,
            incident_id=incident_id,
            commit=True,
        )
        assert second.id == first_id
        assert second.idempotent_hit is True

        # Immutable: UPDATE denied
        denied = False
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE eval.operational_evaluation
                    SET passed = NOT passed
                    WHERE id = %s
                    """,
                    (str(first_id),),
                )
            conn.commit()
        except psycopg.Error:
            conn.rollback()
            denied = True
        assert denied

    headers = {"Authorization": "Bearer local-dev-evaluator"}
    res = client.post(
        f"/eval/scenario-runs/{outcome.run_id}/operational-evaluation",
        headers=headers,
        json={"incident_id": str(incident_id)},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == str(first_id)
    assert body["idempotent_hit"] is True
    assert body["pinned_incident_revision"] == rev

    got = client.get(
        f"/eval/operational-evaluations/{first_id}",
        headers=headers,
    )
    assert got.status_code == 200
    assert got.json()["id"] == str(first_id)


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0023 not reachable")
def test_pin_requires_resolved(client: TestClient) -> None:
    outcome = run_scenario(
        "bad_deploy",
        baseline_fn=lambda: BaselineGateResult(ok=True, payload={}, detail="ok"),
        inject=False,
    )
    with get_runner_conn() as conn:
        mark_fault_injected(conn, run_id=outcome.run_id)

    with psycopg.connect(_app_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO domain.incident (
                    public_id, state, title, incident_revision
                ) VALUES (%s, 'INVESTIGATING', 'n6 early', 1)
                RETURNING id
                """,
                (f"INC-N6E-{uuid.uuid4().hex[:8]}",),
            )
            iid = cur.fetchone()[0]
        conn.commit()

    res = client.post(
        f"/eval/scenario-runs/{outcome.run_id}/operational-evaluation",
        headers={"Authorization": "Bearer local-dev-evaluator"},
        json={"incident_id": str(iid)},
    )
    assert res.status_code == 409
    assert "RESOLVED" in res.json()["detail"]


def test_openapi_n6_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/eval/scenario-runs/{run_id}/operational-evaluation" in paths
    assert "/eval/operational-evaluations/{evaluation_id}" in paths
