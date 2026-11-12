"""OperationalEvaluation pin at RESOLVED (N6) — immutable + idempotent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from incidentpilot_shared.eval_metrics import (
    IncidentScoreInput,
    evaluate_operational,
    parse_root_cause_match_spec,
)
from incidentpilot_shared.scenario_lifecycle import (
    IllegalScenarioTransition,
    mark_evaluated,
)


class OperationalEvalError(Exception):
    """Raised when operational pin preconditions fail."""


@dataclass(frozen=True)
class OperationalEvaluationView:
    id: UUID
    scenario_run_id: UUID
    incident_id: UUID
    pinned_incident_revision: int
    environment_manifest_id: UUID | None
    ground_truth_id: UUID | None
    ground_truth_version: int | None
    scenario_key: str
    passed: bool
    score: float | None
    hard_fail: bool
    threshold: float
    metrics_payload: list[dict[str, Any]]
    summary: dict[str, Any]
    metric_engine_version: str
    created_at: Any
    idempotent_hit: bool = False


def _row_to_view(
    row: dict[str, Any], *, idempotent_hit: bool = False
) -> OperationalEvaluationView:
    return OperationalEvaluationView(
        id=UUID(str(row["id"])),
        scenario_run_id=UUID(str(row["scenario_run_id"])),
        incident_id=UUID(str(row["incident_id"])),
        pinned_incident_revision=int(row["pinned_incident_revision"]),
        environment_manifest_id=(
            UUID(str(row["environment_manifest_id"]))
            if row.get("environment_manifest_id") is not None
            else None
        ),
        ground_truth_id=(
            UUID(str(row["ground_truth_id"]))
            if row.get("ground_truth_id") is not None
            else None
        ),
        ground_truth_version=(
            int(row["ground_truth_version"])
            if row.get("ground_truth_version") is not None
            else None
        ),
        scenario_key=str(row["scenario_key"]),
        passed=bool(row["passed"]),
        score=float(row["score"]) if row.get("score") is not None else None,
        hard_fail=bool(row["hard_fail"]),
        threshold=float(row["threshold"]),
        metrics_payload=list(row.get("metrics_payload") or []),
        summary=dict(row.get("summary") or {}),
        metric_engine_version=str(row["metric_engine_version"]),
        created_at=row.get("created_at"),
        idempotent_hit=idempotent_hit,
    )


def get_operational_evaluation(
    conn: Connection, *, evaluation_id: UUID
) -> OperationalEvaluationView:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM eval.operational_evaluation WHERE id = %s",
            (str(evaluation_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise KeyError(f"unknown operational_evaluation: {evaluation_id}")
    return _row_to_view(dict(row))


def get_operational_evaluation_for_run(
    conn: Connection, *, scenario_run_id: UUID
) -> OperationalEvaluationView | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM eval.operational_evaluation
            WHERE scenario_run_id = %s
            """,
            (str(scenario_run_id),),
        )
        row = cur.fetchone()
    return _row_to_view(dict(row), idempotent_hit=True) if row else None


def collect_incident_score_input(
    conn: Connection, *, incident_id: UUID
) -> IncidentScoreInput:
    """Build N5 IncidentScoreInput from domain SoR (evaluator SELECT)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT evidence_key, id::text AS id_text
            FROM domain.evidence
            WHERE incident_id = %s
            """,
            (str(incident_id),),
        )
        known: set[str] = set()
        for r in cur.fetchall():
            known.add(str(r["evidence_key"]))
            known.add(str(r["id_text"]))

        cur.execute(
            """
            SELECT status, hypothesis_class, cited_evidence_ids
            FROM domain.hypothesis
            WHERE incident_id = %s
            """,
            (str(incident_id),),
        )
        cited: set[str] = set()
        confirmed_class: str | None = None
        for r in cur.fetchall():
            for eid in r.get("cited_evidence_ids") or []:
                cited.add(str(eid))
            if r["status"] == "CONFIRMED" and r.get("hypothesis_class"):
                confirmed_class = str(r["hypothesis_class"])

        cur.execute(
            """
            SELECT s.key
            FROM domain.incident_service isv
            JOIN domain.service s ON s.id = isv.service_id
            WHERE isv.incident_id = %s
            """,
            (str(incident_id),),
        )
        services = {str(r["key"]) for r in cur.fetchall()}

        cur.execute(
            """
            SELECT DISTINCT c.change_type
            FROM domain.change c
            JOIN domain.service s ON s.id = c.service_id
            JOIN domain.incident_service isv ON isv.service_id = s.id
            WHERE isv.incident_id = %s
            """,
            (str(incident_id),),
        )
        changes = {str(r["change_type"]) for r in cur.fetchall()}

        cur.execute(
            """
            SELECT DISTINCT action_type
            FROM domain.action
            WHERE incident_id = %s
              AND status IN ('SUCCEEDED', 'EXECUTING', 'APPROVED', 'FAILED')
            """,
            (str(incident_id),),
        )
        actions = {str(r["action_type"]) for r in cur.fetchall()}

        cur.execute(
            "SELECT severity FROM domain.incident WHERE id = %s",
            (str(incident_id),),
        )
        sev_row = cur.fetchone()
        severity = (
            str(sev_row["severity"])
            if sev_row and sev_row.get("severity") is not None
            else None
        )

    return IncidentScoreInput(
        confirmed_hypothesis_class=confirmed_class,
        known_evidence_ids=frozenset(known),
        cited_evidence_ids=frozenset(cited),
        observed_origin_service_keys=frozenset(services),
        observed_change_types=frozenset(changes),
        executed_action_types=frozenset(actions),
        severity=severity,
    )


def pin_operational_evaluation(
    conn: Connection,
    *,
    scenario_run_id: UUID,
    incident_id: UUID,
    threshold: float = 0.7,
    commit: bool = True,
) -> OperationalEvaluationView:
    """Pin operational score at RESOLVED. Idempotent on scenario_run_id.

    Later AI/domain mutations cannot change the pin (immutable table).
    """
    existing = get_operational_evaluation_for_run(
        conn, scenario_run_id=scenario_run_id
    )
    if existing is not None:
        return existing

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT state, incident_revision
            FROM domain.incident
            WHERE id = %s
            """,
            (str(incident_id),),
        )
        inc = cur.fetchone()
        if inc is None:
            raise OperationalEvalError(f"incident not found: {incident_id}")
        if str(inc["state"]) != "RESOLVED":
            raise OperationalEvalError(
                f"operational pin requires RESOLVED (got {inc['state']})"
            )
        revision = int(inc["incident_revision"])

        cur.execute(
            """
            SELECT r.id, r.status, r.environment_manifest_id, s.key AS scenario_key
            FROM scenarios.scenario_run r
            JOIN scenarios.scenario s ON s.id = r.scenario_id
            WHERE r.id = %s
            """,
            (str(scenario_run_id),),
        )
        run = cur.fetchone()
        if run is None:
            raise OperationalEvalError(f"scenario_run not found: {scenario_run_id}")
        if str(run["status"]) == "FAILED":
            raise OperationalEvalError(
                "cannot pin operational eval on FAILED ScenarioRun"
            )
        scenario_key = str(run["scenario_key"])
        manifest_id = run.get("environment_manifest_id")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, version, match_spec, expected_hypothesis_class,
                   origin_service_keys, expected_action_types, expected_severity
            FROM eval.ground_truth
            WHERE scenario_key = %s
            """,
            (scenario_key,),
        )
        gt = cur.fetchone()
    if gt is None:
        raise OperationalEvalError(f"no ground_truth for scenario_key={scenario_key}")
    gt = dict(gt)

    spec = parse_root_cause_match_spec(
        gt.get("match_spec") if isinstance(gt.get("match_spec"), dict) else {},
        expected_hypothesis_class=gt.get("expected_hypothesis_class"),
        origin_service_keys=list(gt.get("origin_service_keys") or []),
    )
    score_input = collect_incident_score_input(conn, incident_id=incident_id)
    aggregate = evaluate_operational(
        score_input,
        match_spec=spec,
        expected_action_types=list(gt.get("expected_action_types") or []),
        expected_severity=gt.get("expected_severity"),
        threshold=threshold,
    )

    # Align ScenarioRun lifecycle (FAULT_INJECTED or already EVALUATED).
    try:
        if str(run["status"]) == "FAULT_INJECTED":
            mark_evaluated(
                conn,
                run_id=scenario_run_id,
                passed=aggregate.passed,
                summary=aggregate.as_dict(),
                commit=False,
            )
        elif str(run["status"]) == "BASELINE_PASSED":
            # Allow scored harness without inject: promote then evaluate.
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE scenarios.scenario_run
                    SET status = 'FAULT_INJECTED'
                    WHERE id = %s AND status = 'BASELINE_PASSED'
                    """,
                    (str(scenario_run_id),),
                )
            mark_evaluated(
                conn,
                run_id=scenario_run_id,
                passed=aggregate.passed,
                summary=aggregate.as_dict(),
                commit=False,
            )
        elif str(run["status"]) != "EVALUATED":
            raise OperationalEvalError(
                f"scenario_run status {run['status']} not ready for operational pin"
            )
    except IllegalScenarioTransition as exc:
        raise OperationalEvalError(str(exc)) from exc

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scenarios.scenario_run
            SET incident_id = %s
            WHERE id = %s
            """,
            (str(incident_id), str(scenario_run_id)),
        )
        cur.execute(
            """
            INSERT INTO eval.operational_evaluation (
                scenario_run_id, incident_id, pinned_incident_revision,
                environment_manifest_id, ground_truth_id, ground_truth_version,
                scenario_key, passed, score, hard_fail, threshold,
                metrics_payload, summary, metric_engine_version
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s
            )
            ON CONFLICT (scenario_run_id) DO NOTHING
            RETURNING id
            """,
            (
                str(scenario_run_id),
                str(incident_id),
                revision,
                str(manifest_id) if manifest_id is not None else None,
                str(gt["id"]),
                int(gt["version"]),
                scenario_key,
                aggregate.passed,
                aggregate.score,
                aggregate.hard_fail,
                aggregate.threshold,
                Json([m.as_dict() for m in aggregate.metrics]),
                Json(aggregate.as_dict()),
                "n5.v1",
            ),
        )
        inserted = cur.fetchone()

    if commit:
        conn.commit()

    # Race: another pin won — return that row.
    if inserted is None:
        again = get_operational_evaluation_for_run(
            conn, scenario_run_id=scenario_run_id
        )
        if again is None:
            raise OperationalEvalError("operational pin race lost and row missing")
        return again

    return get_operational_evaluation(conn, evaluation_id=UUID(str(inserted[0])))
