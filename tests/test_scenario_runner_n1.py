"""N1: scenario schema, baseline → FAILED, reset keeps history, no GT."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (
    ROOT / "scenario_runner",
    ROOT / "simulation",
    ROOT / "shared",
):
    sys.path.insert(0, str(p))

psycopg = pytest.importorskip("psycopg")

from incidentpilot_scenario_runner.baseline import BaselineGateResult  # noqa: E402
from incidentpilot_scenario_runner.db import (  # noqa: E402
    assert_ground_truth_denied,
    get_runner_conn,
    get_scenario_run,
    list_scenarios,
    mark_reset,
    runner_database_url,
)
from incidentpilot_scenario_runner.runner import run_scenario  # noqa: E402


def _db_available() -> bool:
    try:
        with psycopg.connect(runner_database_url(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM scenarios.scenario LIMIT 1")
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0019 not reachable")
def test_runner_cannot_select_ground_truth() -> None:
    with get_runner_conn() as conn:
        assert_ground_truth_denied(conn)
        # Direct probe must also fail at the driver level
        denied = False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM eval.ground_truth LIMIT 1")
                cur.fetchone()
        except psycopg.Error:
            conn.rollback()
            denied = True
        assert denied, "ip_runner must not SELECT eval.ground_truth"


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0019 not reachable")
def test_catalog_seeded() -> None:
    with get_runner_conn() as conn:
        keys = {r["key"] for r in list_scenarios(conn)}
    assert "bad_deploy" in keys
    assert "cascading_failure" in keys
    assert len(keys) >= 8


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0019 not reachable")
def test_unhealthy_baseline_marks_failed_not_evaluated() -> None:
    def dirty_gate() -> BaselineGateResult:
        return BaselineGateResult(
            ok=False,
            payload={"gateway": {"status": "degraded"}},
            detail="simulated dirty env",
        )

    outcome = run_scenario(
        "bad_deploy",
        baseline_fn=dirty_gate,
        inject=True,
    )
    assert outcome.status == "FAILED"
    assert outcome.failure_kind == "BASELINE"
    assert outcome.baseline_ok is False

    with get_runner_conn() as conn:
        row = get_scenario_run(conn, outcome.run_id)
        assert row["status"] == "FAILED"
        assert row["status"] != "EVALUATED"
        # Reset stamps but keeps the row
        n = mark_reset(conn, run_id=outcome.run_id)
        assert n == 1
        again = get_scenario_run(conn, outcome.run_id)
        assert again["reset_at"] is not None
        assert again["status"] == "FAILED"
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM scenarios.scenario_run WHERE id = %s",
                (str(outcome.run_id),),
            )
            assert cur.fetchone()[0] == 1


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0019 not reachable")
def test_baseline_pass_without_inject() -> None:
    def clean_gate() -> BaselineGateResult:
        return BaselineGateResult(ok=True, payload={"ok": True}, detail="ok")

    outcome = run_scenario(
        "dependency_timeout",
        baseline_fn=clean_gate,
        inject=False,
    )
    assert outcome.status == "BASELINE_PASSED"
    assert outcome.baseline_ok is True


@pytest.mark.skipif(not _db_available(), reason="Postgres / migration 0019 not reachable")
def test_cli_run_dirty_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    from incidentpilot_scenario_runner import __main__ as cli

    def dirty_gate() -> BaselineGateResult:
        return BaselineGateResult(ok=False, payload={}, detail="cli dirty")

    # run_scenario uses the name bound in runner.py
    monkeypatch.setattr(
        "incidentpilot_scenario_runner.runner.run_baseline_gate",
        dirty_gate,
    )
    code = cli.main(["run", "queue_backlog", "--no-inject"])
    assert code == 2


def test_cli_help() -> None:
    from incidentpilot_scenario_runner import __main__ as cli

    with pytest.raises(SystemExit) as ei:
        cli.main(["--help"])
    assert ei.value.code == 0
