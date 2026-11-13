"""N9: bad-deployment scored vertical — Level 2 harness → EVALUATED."""

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
yaml = pytest.importorskip("yaml")

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
                    WHERE scenario_key = 'bad_deploy'
                    """
                )
                row = cur.fetchone()
                return row is not None and int(row[0]) >= 2
    except Exception:
        return False


def test_yaml_definition_resolves_aliases() -> None:
    d = resolve_scenario_name("bad-deployment")
    assert d.key == "bad_deploy"
    assert d.autonomy_level == 2
    assert d.harness == "level2"
    assert d.origin_service == "payment"
    assert "ROLLBACK_DEPLOYMENT" in d.expected_action_types

    d2 = resolve_scenario_name("bad_deployment")
    assert d2.key == "bad_deploy"
    d3 = resolve_scenario_name("bad_deploy")
    assert d3.key == "bad_deploy"


def test_gemini_factory_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    from incidentpilot_adapters.llm import resolve_llm_provider

    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert resolve_llm_provider().name == "fake"

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        resolve_llm_provider()

    monkeypatch.setenv("LLM_API_KEY", "test-not-a-real-key")
    monkeypatch.setenv("LLM_MODEL", "gemini-2.0-flash")
    provider = resolve_llm_provider()
    assert provider.name == "gemini"


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0025 not reachable")
def test_scored_vertical_evaluated_with_family_and_manifest() -> None:
    scored = run_scored_vertical(
        "bad-deployment",
        require_isolation=True,
        inject=False,
    )
    assert scored.scenario_key == "bad_deploy"
    assert scored.environment_manifest_id is not None
    assert scored.status == "RESOLVED_PENDING_EVAL"

    evaluated = evaluate_scored_vertical(
        run_id=scored.run_id,
        incident_id=scored.incident_id,
        name="bad-deployment",
    )
    assert evaluated.status == "EVALUATED"
    assert evaluated.family_count == 2
    assert evaluated.environment_manifest_id is not None
    assert evaluated.operational_evaluation_id is not None
    assert evaluated.postmortem_evaluation_id is not None
    # Pass T/F both ok for AC; well-seeded path should pass.
    assert evaluated.passed_operational is True
    assert evaluated.passed_postmortem is True

    # Runner must still be denied GT (N8 / AC: no GT in IP).
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
                SELECT decided_by FROM domain.approval WHERE id = %s
                """,
                (str(scored.approval_id),),
            )
            row = cur.fetchone()
            assert row is not None
            assert str(row[0]).startswith("harness:")

            cur.execute(
                """
                SELECT version,
                       match_spec->'root_cause'->>'hypothesis_class'
                FROM eval.ground_truth WHERE scenario_key = 'bad_deploy'
                """
            )
            ver, hyp = cur.fetchone()
            assert int(ver) >= 2
            assert hyp == "bad_deployment"
