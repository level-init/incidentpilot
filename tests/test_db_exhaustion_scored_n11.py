"""N11: db-exhaustion scored scenario — Level 2 harness → EVALUATED."""

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


def _db_available() -> bool:
    try:
        with psycopg.connect(_eval_dsn(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT version FROM eval.ground_truth
                    WHERE scenario_key = 'db_exhaustion'
                    """
                )
                row = cur.fetchone()
                return row is not None and int(row[0]) >= 2
    except Exception:
        return False


def test_yaml_definition_resolves_aliases() -> None:
    d = resolve_scenario_name("db-exhaustion")
    assert d.key == "db_exhaustion"
    assert d.autonomy_level == 2
    assert d.origin_service == "inventory"
    assert d.primary_action_type == "SCALE_WORKLOAD"
    assert d.expected_hypothesis_class == "resource_exhaustion"
    assert d.seed_change_type is None
    assert d.action_parameters.get("replicas") == 4
    assert resolve_scenario_name("db_exhaustion").key == "db_exhaustion"
    assert resolve_scenario_name("database-exhaustion").key == "db_exhaustion"


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0027 not reachable")
def test_scored_vertical_evaluated_with_family_and_manifest() -> None:
    scored = run_scored_vertical(
        "db-exhaustion",
        require_isolation=True,
        inject=False,
    )
    assert scored.scenario_key == "db_exhaustion"
    assert scored.environment_manifest_id is not None

    evaluated = evaluate_scored_vertical(
        run_id=scored.run_id,
        incident_id=scored.incident_id,
        name="db-exhaustion",
    )
    assert evaluated.status == "EVALUATED"
    assert evaluated.family_count == 2
    assert evaluated.passed_operational is True
    assert evaluated.passed_postmortem is True

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
                "SELECT action_type FROM domain.action WHERE id = %s",
                (str(scored.action_id),),
            )
            assert cur.fetchone()[0] == "SCALE_WORKLOAD"
            cur.execute(
                """
                SELECT version,
                       match_spec->'root_cause'->>'hypothesis_class',
                       expected_action_types
                FROM eval.ground_truth
                WHERE scenario_key = 'db_exhaustion'
                """
            )
            ver, hyp, actions = cur.fetchone()
            assert int(ver) >= 2
            assert hyp == "resource_exhaustion"
            assert "SCALE_WORKLOAD" in list(actions)
