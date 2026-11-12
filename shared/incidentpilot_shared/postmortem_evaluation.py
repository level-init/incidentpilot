"""PostmortemEvaluation pin at CLOSED (N7) — links OperationalEvaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Json

from incidentpilot_shared.eval_metrics.postmortem import (
    PostmortemScoreInput,
    evaluate_postmortem,
)
from incidentpilot_shared.operational_evaluation import (
    get_operational_evaluation_for_run,
)


class PostmortemEvalError(Exception):
    """Raised when postmortem pin preconditions fail."""


@dataclass(frozen=True)
class PostmortemEvaluationView:
    id: UUID
    scenario_run_id: UUID
    operational_evaluation_id: UUID
    incident_id: UUID
    postmortem_id: UUID
    pinned_incident_revision: int
    environment_manifest_id: UUID | None
    ground_truth_id: UUID | None
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
) -> PostmortemEvaluationView:
    return PostmortemEvaluationView(
        id=UUID(str(row["id"])),
        scenario_run_id=UUID(str(row["scenario_run_id"])),
        operational_evaluation_id=UUID(str(row["operational_evaluation_id"])),
        incident_id=UUID(str(row["incident_id"])),
        postmortem_id=UUID(str(row["postmortem_id"])),
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


def get_postmortem_evaluation(
    conn: Connection, *, evaluation_id: UUID
) -> PostmortemEvaluationView:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM eval.postmortem_evaluation WHERE id = %s",
            (str(evaluation_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise KeyError(f"unknown postmortem_evaluation: {evaluation_id}")
    return _row_to_view(dict(row))


def get_postmortem_evaluation_for_run(
    conn: Connection, *, scenario_run_id: UUID
) -> PostmortemEvaluationView | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM eval.postmortem_evaluation
            WHERE scenario_run_id = %s
            """,
            (str(scenario_run_id),),
        )
        row = cur.fetchone()
    return _row_to_view(dict(row), idempotent_hit=True) if row else None


def collect_postmortem_score_input(
    conn: Connection, *, incident_id: UUID
) -> tuple[PostmortemScoreInput, UUID]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, status, corrective_actions, cited_evidence_ids, provenance
            FROM domain.postmortem
            WHERE incident_id = %s
            ORDER BY CASE status WHEN 'FINAL' THEN 0 ELSE 1 END, created_at DESC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        pm = cur.fetchone()
        if pm is None:
            raise PostmortemEvalError("postmortem required for postmortem evaluation")

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

    cited = {str(x) for x in (pm.get("cited_evidence_ids") or [])}
    actions = pm.get("corrective_actions") or []
    if not isinstance(actions, list):
        actions = []
    prov = pm.get("provenance") or {}
    claims = prov.get("claims") if isinstance(prov, dict) else None
    claim_count = len(claims) if isinstance(claims, list) else 0
    # FINAL rows were citation-validated at write time; treat residual as 0.
    unsupported = 0

    inp = PostmortemScoreInput(
        postmortem_status=str(pm["status"]),
        corrective_actions_count=len(actions),
        known_evidence_ids=frozenset(known),
        cited_evidence_ids=frozenset(cited),
        unsupported_claim_count=unsupported,
        claim_count=claim_count,
    )
    return inp, UUID(str(pm["id"]))


def pin_postmortem_evaluation(
    conn: Connection,
    *,
    scenario_run_id: UUID,
    incident_id: UUID,
    threshold: float = 0.7,
    commit: bool = True,
) -> PostmortemEvaluationView:
    """Pin postmortem-stage score at CLOSED. Requires operational pin + same manifest."""
    existing = get_postmortem_evaluation_for_run(
        conn, scenario_run_id=scenario_run_id
    )
    if existing is not None:
        return existing

    ops = get_operational_evaluation_for_run(conn, scenario_run_id=scenario_run_id)
    if ops is None:
        raise PostmortemEvalError(
            "operational evaluation required before postmortem pin"
        )
    if ops.incident_id != incident_id:
        raise PostmortemEvalError(
            "incident_id does not match operational evaluation incident"
        )

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
            raise PostmortemEvalError(f"incident not found: {incident_id}")
        if str(inc["state"]) != "CLOSED":
            raise PostmortemEvalError(
                f"postmortem pin requires CLOSED (got {inc['state']})"
            )
        revision = int(inc["incident_revision"])

        # Same manifest family as operational pin.
        if ops.environment_manifest_id is not None:
            cur.execute(
                """
                SELECT environment_manifest_id
                FROM scenarios.scenario_run
                WHERE id = %s
                """,
                (str(scenario_run_id),),
            )
            run = cur.fetchone()
            if run is None:
                raise PostmortemEvalError(
                    f"scenario_run not found: {scenario_run_id}"
                )
            run_mid = run.get("environment_manifest_id")
            if run_mid is not None and UUID(str(run_mid)) != ops.environment_manifest_id:
                raise PostmortemEvalError(
                    "environment_manifest mismatch vs operational evaluation"
                )

    score_input, postmortem_id = collect_postmortem_score_input(
        conn, incident_id=incident_id
    )
    aggregate = evaluate_postmortem(score_input, threshold=threshold)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO eval.postmortem_evaluation (
                scenario_run_id, operational_evaluation_id, incident_id,
                postmortem_id, pinned_incident_revision, environment_manifest_id,
                ground_truth_id, scenario_key, passed, score, hard_fail, threshold,
                metrics_payload, summary, metric_engine_version
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s
            )
            ON CONFLICT (scenario_run_id) DO NOTHING
            RETURNING id
            """,
            (
                str(scenario_run_id),
                str(ops.id),
                str(incident_id),
                str(postmortem_id),
                revision,
                str(ops.environment_manifest_id)
                if ops.environment_manifest_id is not None
                else None,
                str(ops.ground_truth_id) if ops.ground_truth_id is not None else None,
                ops.scenario_key,
                aggregate.passed,
                aggregate.score,
                aggregate.hard_fail,
                aggregate.threshold,
                Json([m.as_dict() for m in aggregate.metrics]),
                Json(aggregate.as_dict()),
                "n7.v1",
            ),
        )
        inserted = cur.fetchone()

    if commit:
        conn.commit()

    if inserted is None:
        again = get_postmortem_evaluation_for_run(
            conn, scenario_run_id=scenario_run_id
        )
        if again is None:
            raise PostmortemEvalError("postmortem pin race lost and row missing")
        return again

    return get_postmortem_evaluation(conn, evaluation_id=UUID(str(inserted[0])))


def list_evaluation_family(
    conn: Connection, *, scenario_run_id: UUID
) -> dict[str, Any]:
    """Return both evaluation results for a scored run family (N7 AC)."""
    ops = get_operational_evaluation_for_run(conn, scenario_run_id=scenario_run_id)
    pm = get_postmortem_evaluation_for_run(conn, scenario_run_id=scenario_run_id)
    return {
        "scenario_run_id": str(scenario_run_id),
        "operational_evaluation": None
        if ops is None
        else {
            "id": str(ops.id),
            "stage": "operational",
            "passed": ops.passed,
            "environment_manifest_id": (
                str(ops.environment_manifest_id)
                if ops.environment_manifest_id
                else None
            ),
        },
        "postmortem_evaluation": None
        if pm is None
        else {
            "id": str(pm.id),
            "stage": "postmortem",
            "passed": pm.passed,
            "operational_evaluation_id": str(pm.operational_evaluation_id),
            "environment_manifest_id": (
                str(pm.environment_manifest_id)
                if pm.environment_manifest_id
                else None
            ),
        },
        "count": sum(1 for x in (ops, pm) if x is not None),
    }
