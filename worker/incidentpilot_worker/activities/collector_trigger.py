"""COLLECTOR_TRIGGER activity — general worker only (G7).

Starts ``CollectCycleWorkflow`` on the evidence queue. Never imports Prom/Loki/
Tempo clients or reads their env vars — evidence-worker holds source creds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from temporalio import activity
from temporalio.exceptions import ApplicationError

from incidentpilot_shared.collect_job import (
    ALLOWED_COLLECTORS,
    CollectJob,
    ensure_collect_cycle_started,
)
from incidentpilot_shared.tool_scope import ScopeViolationError, normalize_environment

UNSUPPORTED_COLLECTOR_ERROR_TYPE = "UnsupportedCollector"


@dataclass
class TriggerCollectCycleInput:
    """Payload for ``trigger_collect_cycle`` (tool args + bound environment)."""

    incident_id: str
    environment: str
    collector: str
    query: str
    cycle_id: str | None = None
    window_start: float | None = None
    window_end: float | None = None


def _input_from_payload(
    payload: TriggerCollectCycleInput | dict[str, Any],
) -> TriggerCollectCycleInput:
    if isinstance(payload, TriggerCollectCycleInput):
        return payload
    return TriggerCollectCycleInput(
        incident_id=str(payload["incident_id"]),
        environment=str(payload["environment"]),
        collector=str(payload["collector"]),
        query=str(payload.get("query") or "up"),
        cycle_id=str(payload["cycle_id"]) if payload.get("cycle_id") else None,
        window_start=payload.get("window_start"),
        window_end=payload.get("window_end"),
    )


@activity.defn(name="trigger_collect_cycle")
async def trigger_collect_cycle(
    payload: TriggerCollectCycleInput | dict[str, Any],
) -> dict[str, Any]:
    """Schedule a CollectJob on the evidence queue (no telemetry credentials)."""
    inp = _input_from_payload(payload)
    collector = inp.collector.strip().lower()
    if collector not in ALLOWED_COLLECTORS:
        raise ApplicationError(
            f"unsupported collector {collector!r}; allowed={sorted(ALLOWED_COLLECTORS)}",
            type=UNSUPPORTED_COLLECTOR_ERROR_TYPE,
            non_retryable=True,
        )
    try:
        env = normalize_environment(inp.environment)
    except ScopeViolationError as exc:
        raise ApplicationError(
            str(exc),
            type="CollectJobScopeViolation",
            non_retryable=True,
        ) from exc

    job = CollectJob(
        incident_id=inp.incident_id,
        environment=env,
        cycle_id=inp.cycle_id or str(uuid4()),
        window_start=inp.window_start,
        window_end=inp.window_end,
        collectors=(collector,),
        query=inp.query,
    )
    client = activity.client()
    started = await ensure_collect_cycle_started(client, job)
    return {
        "incident_id": job.incident_id,
        "environment": job.environment,
        "cycle_id": job.cycle_id,
        "collector": collector,
        "started": started,
        "workflow_id": f"collect-{job.incident_id}-{job.cycle_id}",
    }
