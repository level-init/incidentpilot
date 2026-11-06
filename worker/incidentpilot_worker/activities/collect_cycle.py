"""Collect-cycle activities (evidence-worker only) — G6.

Scope is validated against Postgres + ToolScope. Queue membership is not authz.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from temporalio import activity
from temporalio.exceptions import ApplicationError

from incidentpilot_shared.collect_job import CollectJob, EvidenceUpdated
from incidentpilot_shared.tool_scope import (
    ScopeViolationError,
    ToolScope,
    enforce_tool_scope,
    normalize_environment,
)
from incidentpilot_worker.collectors import (
    collect_logs_for_incident,
    collect_metrics_for_incident,
    collect_traces_for_incident,
)
from incidentpilot_worker.db import connect

SCOPE_VIOLATION_ERROR_TYPE = "CollectJobScopeViolation"


def _job_from_payload(payload: CollectJob | dict[str, Any]) -> CollectJob:
    if isinstance(payload, CollectJob):
        return payload
    collectors = payload.get("collectors") or ("metrics", "logs", "traces")
    cycle_id = payload.get("cycle_id")
    return CollectJob(
        incident_id=str(payload["incident_id"]),
        environment=str(payload["environment"]),
        cycle_id=str(cycle_id) if cycle_id else str(uuid4()),
        window_start=payload.get("window_start"),
        window_end=payload.get("window_end"),
        collectors=tuple(collectors),
        query=payload.get("query"),
    )


@activity.defn(name="validate_collect_job_scope")
def validate_collect_job_scope(payload: CollectJob | dict[str, Any]) -> dict[str, Any]:
    """Fail closed if incident missing or job widens beyond server-bound scope."""
    job = _job_from_payload(payload)
    try:
        env = normalize_environment(job.environment)
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM domain.incident WHERE id = %s",
                (job.incident_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ScopeViolationError(f"incident not found: {job.incident_id!r}")
            incident_id = str(row[0])

            scope = ToolScope(incident_id=incident_id, environment=env)
            enforce_tool_scope(
                scope,
                arguments={
                    "incident_id": job.incident_id,
                    "environment": job.environment,
                },
            )

            cur.execute(
                """
                SELECT DISTINCT s.environment
                FROM domain.incident_service isv
                JOIN domain.service s ON s.id = isv.service_id
                WHERE isv.incident_id = %s
                """,
                (incident_id,),
            )
            linked_envs = {normalize_environment(str(r[0])) for r in cur.fetchall()}
            if linked_envs and env not in linked_envs:
                raise ScopeViolationError(
                    f"cross-env access denied: job env={env!r} "
                    f"not in linked service envs={sorted(linked_envs)!r}"
                )
    except ScopeViolationError as exc:
        raise ApplicationError(
            str(exc),
            type=SCOPE_VIOLATION_ERROR_TYPE,
            non_retryable=True,
        ) from exc

    return {
        "incident_id": incident_id,
        "environment": env,
        "cycle_id": job.cycle_id,
        "collectors": list(job.collectors),
    }


@activity.defn(name="run_collect_cycle")
def run_collect_cycle(payload: CollectJob | dict[str, Any]) -> dict[str, Any]:
    """Run selected collectors for the job window; return EvidenceUpdated fields."""
    job = _job_from_payload(payload)
    iid = UUID(job.incident_id)
    now = datetime.now(tz=UTC).timestamp()
    end = job.window_end if job.window_end is not None else now
    start = job.window_start if job.window_start is not None else end - 900

    results = []
    for name in job.collectors:
        if name == "metrics":
            kwargs: dict[str, Any] = {
                "incident_id": iid,
                "start": start,
                "end": end,
                "blob_store": None,
            }
            if job.query:
                kwargs["query"] = job.query
            results.append(collect_metrics_for_incident(**kwargs))
        elif name == "logs":
            kwargs = {
                "incident_id": iid,
                "start": start,
                "end": end,
                "blob_store": None,
            }
            if job.query:
                kwargs["query"] = job.query
            results.append(collect_logs_for_incident(**kwargs))
        elif name == "traces":
            kwargs = {
                "incident_id": iid,
                "start": start,
                "end": end,
                "blob_store": None,
            }
            if job.query:
                kwargs["query"] = job.query
            results.append(collect_traces_for_incident(**kwargs))

    evidence_ids = [str(r.evidence_id) for r in results if r.evidence_id]
    kinds = [r.kind for r in results]
    inserted = sum(1 for r in results if r.inserted)
    updated = EvidenceUpdated(
        incident_id=job.incident_id,
        cycle_id=job.cycle_id,
        evidence_ids=evidence_ids,
        kinds=kinds,
        inserted_count=inserted,
    )
    return {
        "incident_id": updated.incident_id,
        "cycle_id": updated.cycle_id,
        "evidence_ids": updated.evidence_ids,
        "kinds": updated.kinds,
        "inserted_count": updated.inserted_count,
    }
