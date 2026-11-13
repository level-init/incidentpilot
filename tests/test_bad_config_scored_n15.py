"""N15: bad-config/flag scored scenario — Level 2 harness → EVALUATED."""

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
                    SELECT version, expected_action_types
                    FROM eval.ground_truth
                    WHERE scenario_key = 'bad_config'
                    """
                )
                row = cur.fetchone()
                return (
                    row is not None
                    and int(row[0]) >= 2
                    and "DISABLE_FEATURE_FLAG" in list(row[1])
                )
    except Exception:
        return False


def test_yaml_definition_resolves_aliases() -> None:
    d = resolve_scenario_name("bad-config")
    assert d.key == "bad_config"
    assert d.origin_service == "auth"
    assert d.primary_action_type == "DISABLE_FEATURE_FLAG"
    assert d.seed_change_type == "FEATURE_FLAG"
    assert resolve_scenario_name("bad-flag").key == "bad_config"
    assert resolve_scenario_name("bad_config").key == "bad_config"


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0031 not reachable")
def test_scored_vertical_evaluated_with_family_and_manifest() -> None:
    scored = run_scored_vertical(
        "bad-config",
        require_isolation=True,
        inject=False,
    )
    assert scored.scenario_key == "bad_config"

    evaluated = evaluate_scored_vertical(
        run_id=scored.run_id,
        incident_id=scored.incident_id,
        name="bad-config",
    )
    assert evaluated.status == "EVALUATED"
    assert evaluated.family_count == 2
    assert evaluated.passed_operational is True
    assert evaluated.passed_postmortem is True
    assert evaluated.scenario_key == "bad_config"

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
            assert cur.fetchone()[0] == "DISABLE_FEATURE_FLAG"
            cur.execute(
                """
                SELECT version, expected_action_types,
                       match_spec->'root_cause'->>'hypothesis_class'
                FROM eval.ground_truth
                WHERE scenario_key = 'bad_config'
                """
            )
            ver, actions, hyp = cur.fetchone()
            assert int(ver) >= 2
            assert list(actions) == ["DISABLE_FEATURE_FLAG"]
            assert hyp == "bad_config"
            assert "TOGGLE_FEATURE_FLAG" not in list(actions)
