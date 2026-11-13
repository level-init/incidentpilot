"""Scored scenario verticals (N9+) — Level 2 harness path to dual-stage eval.

Does **not** read GroundTruth (evaluator pins do). Isolation must be green
before scoring (``make test-isolation`` / ``--require-isolation``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from incidentpilot_scenario_runner.baseline import BaselineGateResult
from incidentpilot_scenario_runner.db import get_runner_conn, mark_fault_injected
from incidentpilot_scenario_runner.definitions import (
    ScenarioDefinition,
    resolve_scenario_name,
)
from incidentpilot_scenario_runner.runner import run_scenario

_ROOT = Path(__file__).resolve().parents[2]
_CACHE = _ROOT / ".cache" / "last_scenario_run.json"


@dataclass(frozen=True)
class ScoredVerticalResult:
    scenario_key: str
    run_id: UUID
    incident_id: UUID
    approval_id: UUID
    action_id: UUID
    status: str
    environment_manifest_id: str | None
    operational_evaluation_id: str | None = None
    postmortem_evaluation_id: str | None = None
    family_count: int | None = None
    passed_operational: bool | None = None
    passed_postmortem: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["run_id"] = str(self.run_id)
        d["incident_id"] = str(self.incident_id)
        d["approval_id"] = str(self.approval_id)
        d["action_id"] = str(self.action_id)
        return d


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


def _write_cache(payload: dict[str, Any]) -> None:
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def read_cache() -> dict[str, Any] | None:
    if not _CACHE.is_file():
        return None
    raw = json.loads(_CACHE.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def ensure_isolation_green(*, skip: bool = False) -> None:
    """Fail fast unless N8 isolation suite is green."""
    if skip:
        return
    scan = _ROOT / "scripts" / "scan_isolation_integrity.py"
    proc = subprocess.run(
        [sys.executable, str(scan)],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "isolation scan failed — run `make test-isolation` before scored runs\n"
            + (proc.stdout or "")
            + (proc.stderr or "")
        )


def _default_action_parameters(action_type: str, *, service: str) -> dict[str, Any]:
    if action_type == "ROLLBACK_DEPLOYMENT":
        return {"revision": "prev", "deployment": "checkout"}
    if action_type == "REROUTE_TRAFFIC":
        return {"service": service, "weights": {"primary": 0, "drain": 100}}
    if action_type == "RESTART_WORKLOAD":
        return {"workload": service}
    if action_type == "SCALE_WORKLOAD":
        return {"workload": service, "replicas": 4}
    return {}


def _drive_level2_path(
    conn: Any,
    *,
    definition: ScenarioDefinition,
) -> tuple[UUID, UUID, UUID]:
    """Propose action → REQUIRE_APPROVAL → harness APPROVED → SUCCEEDED.

    Returns (incident_id, action_id, approval_id).
    """
    from incidentpilot_shared.approval_harness import harness_actor_id
    from incidentpilot_shared.domain.commands import (
        create_incident_command,
        create_runbook_command,
        create_runbook_version_command,
        decide_approval_command,
        evaluate_policy_command,
        pin_runbook_version_command,
        propose_action_command,
        publish_runbook_version_command,
        upsert_change_command,
    )

    service = definition.origin_service
    action_type = definition.primary_action_type
    params = dict(definition.action_parameters) or _default_action_parameters(
        action_type, service=service
    )

    created = create_incident_command(
        conn,
        title=f"scored {definition.key}",
        severity=definition.expected_severity or "SEV2",
        service_key=service,
        environment="local",
        commit=False,
    )
    incident_id = created.incident_id

    if definition.seed_change_type:
        upsert_change_command(
            conn,
            change_type=definition.seed_change_type,
            service_key=service,
            observed_at=datetime.now(UTC),
            source_ref=f"scored/{definition.key}/{uuid4().hex[:8]}",
            source="scenario_runner",
            fingerprint=f"scored-{definition.key}-{uuid4().hex}",
            summary=f"{definition.key} change seed",
            payload={"scenario": definition.key},
            provenance={"layer": "CHANGE", "scenario": definition.key},
            environment="local",
            commit=False,
        )

    rb = create_runbook_command(
        conn,
        key=f"scored.rb.{uuid4().hex[:8]}",
        title=f"scored {definition.key}",
        service_key=service,
        commit=False,
    )
    ver = create_runbook_version_command(
        conn,
        runbook_id=rb.runbook_id,
        body_markdown=f"# scored {definition.key} — {action_type}",
        allowed_action_types=list(definition.expected_action_types or (action_type,)),
        commit=False,
    )
    published = publish_runbook_version_command(
        conn, runbook_version_id=ver.runbook_version_id, commit=False
    )
    pin_runbook_version_command(
        conn,
        incident_id=incident_id,
        runbook_version_id=published.runbook_version_id,
        commit=False,
    )

    proposed = propose_action_command(
        conn,
        incident_id=incident_id,
        action_type=action_type,
        parameters=params,
        commit=False,
    )
    decision = evaluate_policy_command(
        conn,
        action_id=proposed.action_id,
        actor="system",
        commit=False,
    )
    if decision.decision != "REQUIRE_APPROVAL":
        raise RuntimeError(f"expected REQUIRE_APPROVAL for Level 2, got {decision.decision}")
    if decision.autonomy_level != definition.autonomy_level:
        raise RuntimeError(
            f"expected autonomy_level={definition.autonomy_level}, got {decision.autonomy_level}"
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM domain.approval
            WHERE action_id = %s AND action_version = %s
            """,
            (str(proposed.action_id), proposed.version),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("REQUIRE_APPROVAL did not create a PENDING approval")
        approval_id = UUID(str(row[0]))

    # I6 harness actor (no Slack). Same domain write as /eval/approvals/.../decide.
    decide_approval_command(
        conn,
        action_id=proposed.action_id,
        action_version=proposed.version,
        status="APPROVED",
        decided_by=harness_actor_id(definition.key),
        commit=False,
    )

    # Simulate successful remediation after harness APPROVED (without Temporal).
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE domain.action
            SET status = 'SUCCEEDED', updated_at = now()
            WHERE id = %s
            """,
            (str(proposed.action_id),),
        )
        hyp_class = definition.expected_hypothesis_class or definition.key
        cur.execute(
            """
            INSERT INTO domain.hypothesis (
                incident_id, status, statement, hypothesis_class,
                proposed_by, cited_evidence_ids
            ) VALUES (
                %s, 'CONFIRMED', %s, %s, 'system', '{}'::uuid[]
            )
            """,
            (
                str(incident_id),
                f"{definition.key}: confirmed {hyp_class}",
                hyp_class,
            ),
        )
        cur.execute(
            """
            UPDATE domain.incident
            SET state = 'RESOLVED', incident_revision = incident_revision + 1,
                updated_at = now()
            WHERE id = %s
            """,
            (str(incident_id),),
        )
    return incident_id, proposed.action_id, approval_id


def run_scored_vertical(
    name: str,
    *,
    require_isolation: bool = True,
    inject: bool = False,
) -> ScoredVerticalResult:
    """Create FAULT_INJECTED ScenarioRun + Level-2 path ending RESOLVED."""
    definition = resolve_scenario_name(name)
    ensure_isolation_green(skip=not require_isolation)

    outcome = run_scenario(
        definition.key,
        baseline_fn=lambda: BaselineGateResult(
            ok=True, payload={"scored": True}, detail="scored-vertical-mock"
        ),
        inject=inject,
    )
    if outcome.status == "FAILED":
        raise RuntimeError(f"scenario_run FAILED ({outcome.failure_kind}) — not evaluable")

    with get_runner_conn() as conn:
        if outcome.status == "BASELINE_PASSED":
            mark_fault_injected(conn, run_id=outcome.run_id)
        # Refresh status after possible promote.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, environment_manifest_id
                FROM scenarios.scenario_run WHERE id = %s
                """,
                (str(outcome.run_id),),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(f"scenario_run missing after inject: {outcome.run_id}")
            st, manifest = row[0], row[1]
        if str(st) not in {"FAULT_INJECTED", "EVALUATED"}:
            raise RuntimeError(f"run not ready for scoring: status={st}")

    import psycopg

    with psycopg.connect(_app_dsn()) as conn:
        incident_id, action_id, approval_id = _drive_level2_path(conn, definition=definition)
        conn.commit()

    result = ScoredVerticalResult(
        scenario_key=definition.key,
        run_id=outcome.run_id,
        incident_id=incident_id,
        approval_id=approval_id,
        action_id=action_id,
        status="RESOLVED_PENDING_EVAL",
        environment_manifest_id=str(manifest) if manifest is not None else None,
    )
    _write_cache(
        {
            "scenario_key": definition.key,
            "run_id": str(outcome.run_id),
            "incident_id": str(incident_id),
            "approval_id": str(approval_id),
            "action_id": str(action_id),
            "environment_manifest_id": result.environment_manifest_id,
        }
    )
    return result


def evaluate_scored_vertical(
    *,
    run_id: UUID | None = None,
    incident_id: UUID | None = None,
    name: str | None = None,
) -> ScoredVerticalResult:
    """Pin OperationalEvaluation @ RESOLVED + PostmortemEvaluation @ CLOSED."""
    import psycopg

    from incidentpilot_shared.operational_evaluation import pin_operational_evaluation
    from incidentpilot_shared.postmortem_evaluation import (
        list_evaluation_family,
        pin_postmortem_evaluation,
    )

    cache = read_cache() or {}
    if run_id is None:
        if not cache.get("run_id"):
            raise RuntimeError("no cached scenario run — run `make scenario` first")
        run_id = UUID(str(cache["run_id"]))
    if incident_id is None:
        if not cache.get("incident_id"):
            raise RuntimeError("no cached incident — run `make scenario` first")
        incident_id = UUID(str(cache["incident_id"]))

    scenario_key = str(cache.get("scenario_key") or (name or "bad_deploy"))
    if name:
        scenario_key = resolve_scenario_name(name).key

    with psycopg.connect(_eval_dsn()) as conn:
        ops = pin_operational_evaluation(
            conn,
            scenario_run_id=run_id,
            incident_id=incident_id,
            commit=True,
        )

    # Finalize postmortem + CLOSE for N7 pin.
    with psycopg.connect(_app_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO domain.postmortem (
                    incident_id, status, title, body_markdown, corrective_actions,
                    cited_evidence_ids, author, provenance, finalized_at
                ) VALUES (
                    %s, 'FINAL', %s, %s,
                    '[{"title":"Canary + auto-rollback gate"}]'::jsonb,
                    '{}'::uuid[], 'harness:scored', '{"claims":[]}'::jsonb, now()
                )
                ON CONFLICT (incident_id) DO NOTHING
                """,
                (
                    str(incident_id),
                    f"scored postmortem {scenario_key}",
                    f"Root cause: {scenario_key}. Corrective: harden dependency timeouts.",
                ),
            )
            cur.execute(
                """
                UPDATE domain.incident
                SET state = 'CLOSED', incident_revision = incident_revision + 1,
                    updated_at = now()
                WHERE id = %s AND state = 'RESOLVED'
                """,
                (str(incident_id),),
            )
        conn.commit()

    with psycopg.connect(_eval_dsn()) as conn:
        pm = pin_postmortem_evaluation(
            conn,
            scenario_run_id=run_id,
            incident_id=incident_id,
            commit=True,
        )
        family = list_evaluation_family(conn, scenario_run_id=run_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, passed, environment_manifest_id
                FROM scenarios.scenario_run WHERE id = %s
                """,
                (str(run_id),),
            )
            run_row = cur.fetchone()
            if run_row is None:
                raise RuntimeError(f"scenario_run missing: {run_id}")
            st, _passed, manifest = run_row[0], run_row[1], run_row[2]

    if str(st) != "EVALUATED":
        raise RuntimeError(f"expected EVALUATED, got {st}")
    if int(family["count"]) != 2:
        raise RuntimeError(f"expected evaluation-family count=2, got {family['count']}")
    if manifest is None:
        raise RuntimeError("environment_manifest_id missing on ScenarioRun")

    approval_id = UUID(str(cache.get("approval_id") or uuid4()))
    action_id = UUID(str(cache.get("action_id") or uuid4()))
    result = ScoredVerticalResult(
        scenario_key=scenario_key,
        run_id=run_id,
        incident_id=incident_id,
        approval_id=approval_id,
        action_id=action_id,
        status=str(st),
        environment_manifest_id=str(manifest),
        operational_evaluation_id=str(ops.id),
        postmortem_evaluation_id=str(pm.id),
        family_count=int(family["count"]),
        passed_operational=bool(ops.passed),
        passed_postmortem=bool(pm.passed),
    )
    _write_cache({**(cache or {}), **result.as_dict(), "evaluated": True})
    return result
