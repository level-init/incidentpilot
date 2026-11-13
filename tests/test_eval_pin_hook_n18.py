"""N18: validation/RESOLVED → evaluator hook; workers never read GT."""

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
    ROOT / "worker",
    ROOT / "scenario_runner",
    ROOT / "evaluator",
):
    sys.path.insert(0, str(p))

from incidentpilot_shared.domain.commands import (  # noqa: E402
    record_validation_result_command,
    route_validation_outcome_command,
)
from incidentpilot_shared.eval_pin_hook import (  # noqa: E402
    EVAL_OPERATIONAL_PIN_EVENT,
    assert_eval_pin_payload,
    link_scenario_run_incident,
    request_operational_evaluation_hook,
)
from incidentpilot_scenario_runner.baseline import BaselineGateResult  # noqa: E402
from incidentpilot_scenario_runner.db import (  # noqa: E402
    get_runner_conn,
    mark_fault_injected,
)
from incidentpilot_scenario_runner.runner import run_scenario  # noqa: E402

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
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'domain'
                      AND table_name = 'outbox_message'
                    """
                )
                return cur.fetchone() is not None
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _db_available(), reason="postgres unavailable")


def test_assert_eval_pin_payload_rejects_gt_fields() -> None:
    with pytest.raises(ValueError):
        assert_eval_pin_payload(
            {
                "scenario_run_id": str(uuid.uuid4()),
                "ground_truth_id": str(uuid.uuid4()),
            }
        )
    with pytest.raises(ValueError):
        assert_eval_pin_payload({"incident_id": str(uuid.uuid4())})
    rid = uuid.uuid4()
    assert assert_eval_pin_payload({"scenario_run_id": str(rid)}) == rid


def test_hook_module_does_not_import_ground_truth() -> None:
    text = (ROOT / "shared/incidentpilot_shared/eval_pin_hook.py").read_text(
        encoding="utf-8"
    )
    assert "ground_truth" not in text
    assert "pin_operational_evaluation" not in text
    assert "answer_payload" not in text


@needs_db
def test_worker_creds_cannot_select_ground_truth() -> None:
    with psycopg.connect(_app_dsn()) as conn:
        with conn.cursor() as cur:
            with pytest.raises(psycopg.Error):
                cur.execute("SELECT 1 FROM eval.ground_truth LIMIT 1")
                cur.fetchone()


def _seed_linked_validating_incident() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """FAULT_INJECTED run linked to VALIDATING incident + ValidationResult path."""
    outcome = run_scenario(
        "bad_deploy",
        baseline_fn=lambda: BaselineGateResult(
            ok=True, payload={"n18": True}, detail="n18-mock"
        ),
        inject=False,
    )
    with get_runner_conn() as conn:
        if outcome.status == "BASELINE_PASSED":
            mark_fault_injected(conn, run_id=outcome.run_id)
        run_id = outcome.run_id

    with psycopg.connect(_app_dsn()) as conn:
        with conn.cursor() as cur:
            public_id = f"INC-N18-{uuid.uuid4().hex[:8]}"
            cur.execute(
                """
                INSERT INTO domain.incident (
                    public_id, state, title, severity, incident_revision
                ) VALUES (%s, 'VALIDATING', 'n18 hook', 'SEV2', 2)
                RETURNING id
                """,
                (public_id,),
            )
            incident_id = uuid.UUID(str(cur.fetchone()[0]))
            action_id = uuid.uuid4()
            attempt_id = uuid.uuid4()
            cur.execute(
                """
                INSERT INTO domain.action (
                    id, incident_id, action_type, current_version, status, proposed_by
                ) VALUES (%s, %s, 'ROLLBACK_DEPLOYMENT', 1, 'SUCCEEDED', 'system')
                """,
                (str(action_id), str(incident_id)),
            )
            cur.execute(
                """
                INSERT INTO domain.action_version (
                    action_id, version, action_type, proposed_by
                ) VALUES (%s, 1, 'ROLLBACK_DEPLOYMENT', 'system')
                """,
                (str(action_id),),
            )
            cur.execute(
                """
                INSERT INTO domain.execution_attempt (
                    id, action_id, action_version, attempt_number, state
                ) VALUES (%s, %s, 1, 1, 'SUCCEEDED')
                """,
                (str(attempt_id), str(action_id)),
            )
        conn.commit()

    with get_runner_conn() as conn:
        link_scenario_run_incident(
            conn,
            scenario_run_id=run_id,
            incident_id=incident_id,
            commit=True,
        )

    return run_id, incident_id, attempt_id


@needs_db
def test_j8_resolved_enqueues_scenario_run_id_only() -> None:
    run_id, incident_id, attempt_id = _seed_linked_validating_incident()

    with psycopg.connect(_app_dsn()) as conn:
        record_validation_result_command(
            conn,
            incident_id=incident_id,
            execution_attempt_id=attempt_id,
            outcome="RECOVERED",
            criteria={"n18": True},
            observations={"reason": "n18"},
            transition=False,
            actor="test-n18",
            commit=False,
        )
        routed = route_validation_outcome_command(
            conn,
            incident_id=incident_id,
            execution_attempt_id=attempt_id,
            actor="test-n18",
            commit=True,
        )

    assert routed.route == "RESOLVED"
    assert routed.to_state == "RESOLVED"

    with psycopg.connect(_app_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, event_type, payload
                FROM domain.outbox_message
                WHERE event_type = %s
                  AND aggregate_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (EVAL_OPERATIONAL_PIN_EVENT, str(run_id)),
            )
            row = cur.fetchone()
    assert row is not None
    _mid, event_type, payload = row[0], row[1], row[2]
    if isinstance(payload, str):
        import json

        payload = json.loads(payload)
    assert event_type == EVAL_OPERATIONAL_PIN_EVENT
    assert set(payload.keys()) == {"scenario_run_id"}
    assert payload["scenario_run_id"] == str(run_id)
    assert "ground_truth" not in str(payload).lower()
    assert "answer" not in str(payload).lower()


@needs_db
def test_evaluator_pin_consumer_pins_without_worker_gt() -> None:
    from incidentpilot_evaluator.pin_consumer import pin_once
    from incidentpilot_shared.operational_evaluation import (
        get_operational_evaluation_for_run,
    )

    run_id, incident_id, attempt_id = _seed_linked_validating_incident()

    with psycopg.connect(_app_dsn()) as conn:
        record_validation_result_command(
            conn,
            incident_id=incident_id,
            execution_attempt_id=attempt_id,
            outcome="RECOVERED",
            criteria={"n18": True},
            observations={"reason": "n18-pin"},
            transition=False,
            actor="test-n18",
            commit=False,
        )
        route_validation_outcome_command(
            conn,
            incident_id=incident_id,
            execution_attempt_id=attempt_id,
            actor="test-n18",
            commit=True,
        )

    # Worker/app still cannot read GT even after enqueue.
    test_worker_creds_cannot_select_ground_truth()

    published = pin_once(limit=50, aggregate_id=str(run_id))
    assert published >= 1

    with psycopg.connect(_eval_dsn()) as conn:
        view = get_operational_evaluation_for_run(conn, scenario_run_id=run_id)
    assert view is not None
    assert view.incident_id == incident_id
    assert view.scenario_run_id == run_id


@needs_db
def test_hook_noop_without_linked_run() -> None:
    with psycopg.connect(_app_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO domain.incident (
                    public_id, state, title, severity, incident_revision
                ) VALUES (%s, 'RESOLVED', 'n18 noop', 'SEV3', 1)
                RETURNING id
                """,
                (f"INC-N18N-{uuid.uuid4().hex[:8]}",),
            )
            incident_id = uuid.UUID(str(cur.fetchone()[0]))
        result = request_operational_evaluation_hook(
            conn, incident_id=incident_id, commit=True
        )
    assert result.enqueued is False
    assert result.reason == "no_linked_scenario_run"
