"""N16: cascading-failure scored scenario — Level 2 harness → EVALUATED."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "api",
    ROOT / "shared",
    ROOT / "adapters",
    ROOT / "scenario_runner",
    ROOT / "evaluator",
):
    sys.path.insert(0, str(p))

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("yaml")

from incidentpilot_scenario_runner.definitions import (  # noqa: E402
    resolve_scenario_name,
)
from incidentpilot_scenario_runner.scored import (  # noqa: E402
    evaluate_scored_vertical,
    run_scored_vertical,
)


def _eval_dsn() -> str:
    return os.environ.get(
        "DATABASE_URL_EVALUATOR",
        "postgresql://ip_evaluator:incidentpilot_evaluator@localhost:5432/incidentpilot",
    )


def _app_dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot",
    )


def _db_available() -> bool:
    try:
        with psycopg.connect(_eval_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT version FROM eval.ground_truth
                    WHERE scenario_key = 'cascading_failure'
                    """
                )
                row = cur.fetchone()
                return row is not None and int(row[0]) >= 2
    except Exception:
        return False


def test_yaml_definition_resolves_aliases() -> None:
    d = resolve_scenario_name("cascading-failure")
    assert d.key == "cascading_failure"
    assert d.origin_service == "payment"
    assert "inventory" in d.additional_origin_services
    assert d.all_origin_services == ("payment", "inventory")
    assert d.symptom_services == ("gateway",)
    assert d.primary_action_type == "ROLLBACK_DEPLOYMENT"
    assert d.expected_severity == "SEV1"
    assert "gateway" not in d.all_origin_services  # origin ≠ symptom
    assert resolve_scenario_name("cascading_failure").key == "cascading_failure"


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0032 not reachable")
def test_scored_vertical_evaluated_with_family_and_manifest() -> None:
    scored = run_scored_vertical(
        "cascading-failure",
        require_isolation=True,
        inject=False,
    )
    assert scored.scenario_key == "cascading_failure"

    with psycopg.connect(_app_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.key
                FROM domain.incident_service isv
                JOIN domain.service s ON s.id = isv.service_id
                WHERE isv.incident_id = %s
                ORDER BY s.key
                """,
                (str(scored.incident_id),),
            )
            services = [r[0] for r in cur.fetchall()]
    assert services == ["inventory", "payment"]

    evaluated = evaluate_scored_vertical(
        run_id=scored.run_id,
        incident_id=scored.incident_id,
        name="cascading-failure",
    )
    assert evaluated.status == "EVALUATED"
    assert evaluated.family_count == 2
    assert evaluated.passed_operational is True
    assert evaluated.passed_postmortem is True
    assert evaluated.scenario_key == "cascading_failure"

    from incidentpilot_scenario_runner.db import get_runner_conn

    with get_runner_conn() as rconn:
        denied = False
        try:
            with rconn.cursor() as cur:
                cur.execute("SELECT 1 FROM eval.ground_truth LIMIT 1")
                cur.fetchone()
        except Exception:
            denied = True
            rconn.rollback()
        assert denied

    with psycopg.connect(_eval_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.action_type, i.severity
                FROM domain.action a
                JOIN domain.incident i ON i.id = a.incident_id
                WHERE a.id = %s
                """,
                (str(scored.action_id),),
            )
            action_type, severity = cur.fetchone()
            assert action_type == "ROLLBACK_DEPLOYMENT"
            assert severity == "SEV1"
            cur.execute(
                """
                SELECT version,
                       origin_service_keys,
                       match_spec->'root_cause'->>'origin_ne_symptom'
                FROM eval.ground_truth
                WHERE scenario_key = 'cascading_failure'
                """
            )
            ver, origins, origin_ne = cur.fetchone()
            assert int(ver) >= 2
            assert set(origins) == {"payment", "inventory"}
            assert origin_ne == "true"
