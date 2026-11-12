"""Scenario run orchestration (N1): baseline → inject; reset keeps history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from incidentpilot_scenario_runner.baseline import (
    BaselineGateResult,
    run_baseline_gate,
)
from incidentpilot_scenario_runner.db import (
    assert_ground_truth_denied,
    create_scenario_run,
    get_runner_conn,
    get_scenario_by_key,
    get_scenario_run,
    mark_baseline_passed,
    mark_failed,
    mark_fault_injected,
    mark_reset,
)
from incidentpilot_scenario_runner.inject import activate_injector, reset_injectors


@dataclass(frozen=True)
class RunOutcome:
    run_id: UUID
    scenario_key: str
    status: str
    failure_kind: str | None = None
    failure_detail: str | None = None
    baseline_ok: bool | None = None


def run_scenario(
    scenario_key: str,
    *,
    baseline_fn: Any | None = None,
    inject: bool = True,
) -> RunOutcome:
    """Create a ScenarioRun, gate baseline, optionally inject fault.

    Unhealthy baseline → status FAILED (not EVALUATED).
    """
    gate = baseline_fn or run_baseline_gate

    with get_runner_conn() as conn:
        assert_ground_truth_denied(conn)
        scenario = get_scenario_by_key(conn, scenario_key)
        if not scenario["enabled"]:
            raise RuntimeError(f"scenario disabled: {scenario_key}")
        run_id = create_scenario_run(
            conn,
            scenario_id=scenario["id"],
            injector_id=str(scenario["injector_id"]),
        )

    result: BaselineGateResult = gate()
    with get_runner_conn() as conn:
        if not result.ok:
            mark_failed(
                conn,
                run_id=run_id,
                failure_kind="BASELINE",
                failure_detail=result.detail or "baseline gate failed",
                baseline_ok=False,
                baseline_payload=result.payload,
            )
            row = get_scenario_run(conn, run_id)
            return RunOutcome(
                run_id=run_id,
                scenario_key=scenario_key,
                status=str(row["status"]),
                failure_kind=row.get("failure_kind"),
                failure_detail=row.get("failure_detail"),
                baseline_ok=False,
            )

        mark_baseline_passed(conn, run_id=run_id, baseline_payload=result.payload)

    if not inject:
        with get_runner_conn() as conn:
            row = get_scenario_run(conn, run_id)
        return RunOutcome(
            run_id=run_id,
            scenario_key=scenario_key,
            status=str(row["status"]),
            baseline_ok=True,
        )

    try:
        activate_injector(str(scenario["injector_id"]))
    except Exception as exc:  # noqa: BLE001
        with get_runner_conn() as conn:
            mark_failed(
                conn,
                run_id=run_id,
                failure_kind="INJECT",
                failure_detail=str(exc),
                baseline_ok=True,
                baseline_payload=result.payload,
            )
            row = get_scenario_run(conn, run_id)
        return RunOutcome(
            run_id=run_id,
            scenario_key=scenario_key,
            status=str(row["status"]),
            failure_kind=row.get("failure_kind"),
            failure_detail=row.get("failure_detail"),
            baseline_ok=True,
        )

    with get_runner_conn() as conn:
        mark_fault_injected(conn, run_id=run_id)
        row = get_scenario_run(conn, run_id)

    return RunOutcome(
        run_id=run_id,
        scenario_key=scenario_key,
        status=str(row["status"]),
        baseline_ok=True,
    )


def reset_environment(*, run_id: UUID | None = None) -> dict[str, Any]:
    """Clear sim faults and stamp reset_at — never delete ScenarioRun rows."""
    inject_result = reset_injectors()
    with get_runner_conn() as conn:
        assert_ground_truth_denied(conn)
        stamped = mark_reset(conn, run_id=run_id)
        # Prove history still queryable
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM scenarios.scenario_run")
            history_count = int(cur.fetchone()[0])
    return {
        "injectors": inject_result,
        "runs_stamped": stamped,
        "scenario_run_history_count": history_count,
    }
