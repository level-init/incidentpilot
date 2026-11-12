"""N2: GroundTruth schema + DB isolation (evaluator-only)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "evaluator",
    ROOT / "api",
    ROOT / "shared",
    ROOT / "scenario_runner",
):
    sys.path.insert(0, str(p))

psycopg = pytest.importorskip("psycopg")

from incidentpilot_evaluator.ground_truth import (  # noqa: E402
    app_database_url,
    get_ground_truth,
    get_evaluator_conn,
    list_ground_truth,
    probe_select_denied,
    runner_database_url,
)


def _eval_db_available() -> bool:
    try:
        with get_evaluator_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'eval'
                      AND table_name = 'ground_truth'
                      AND column_name = 'match_spec'
                    """
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@pytest.mark.skipif(not _eval_db_available(), reason="Postgres / migration 0020 not reachable")
def test_ip_app_and_runner_denied_gt_select() -> None:
    assert probe_select_denied(app_database_url()) is True
    assert probe_select_denied(runner_database_url()) is True


@pytest.mark.skipif(not _eval_db_available(), reason="Postgres / migration 0020 not reachable")
def test_evaluator_can_read_structured_gt() -> None:
    with get_evaluator_conn() as conn:
        rows = list_ground_truth(conn)
        keys = {r["scenario_key"] for r in rows}
        assert "bad_deploy" in keys
        assert len(keys) >= 8

        gt = get_ground_truth(conn, scenario_key="bad_deploy")
        assert gt is not None
        assert gt["expected_hypothesis_class"] == "bad_deployment"
        assert "payment" in list(gt["origin_service_keys"])
        assert "ROLLBACK_DEPLOYMENT" in list(gt["expected_action_types"])
        assert isinstance(gt["match_spec"], dict)
        assert "root_cause" in gt["match_spec"]


@pytest.mark.skipif(not _eval_db_available(), reason="Postgres / migration 0020 not reachable")
def test_ip_app_cannot_insert_gt() -> None:
    denied = False
    try:
        with psycopg.connect(app_database_url(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO eval.ground_truth (scenario_key, answer_payload)
                    VALUES ('_n2_should_fail', '{}'::jsonb)
                    """
                )
            conn.commit()
    except psycopg.Error:
        denied = True
    assert denied


@pytest.mark.skipif(not _eval_db_available(), reason="Postgres / migration 0020 not reachable")
def test_eval_api_returns_structured_fields() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from incidentpilot_api.app import app

    client = TestClient(app)
    res = client.get(
        "/eval/ground-truth",
        headers={"Authorization": "Bearer local-dev-evaluator"},
        params={"scenario_key": "cascading_failure"},
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["scenario_key"] == "cascading_failure"
    assert "payment" in row["origin_service_keys"]
    assert row["match_spec"]["root_cause"]["symptom_services"] == ["gateway"]
    assert "answer_payload" in row
