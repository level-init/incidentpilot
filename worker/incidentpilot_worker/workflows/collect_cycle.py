"""CollectCycleWorkflow — evidence-queue collect job + EvidenceUpdated (G6).

Runs only on ``incidentpilot-evidence``. Validates scope server-side, collects,
then signals IncidentWorkflow. Queue membership is not authorization.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from incidentpilot_shared.collect_job import (
        CollectJob,
        EvidenceUpdated,
        collect_cycle_workflow_id,
    )
    from incidentpilot_shared.incident_workflow import incident_workflow_id
    from incidentpilot_worker.activities.collect_cycle import SCOPE_VIOLATION_ERROR_TYPE

__all__ = ["CollectCycleWorkflow", "CollectJob", "collect_cycle_workflow_id"]


@workflow.defn(name="CollectCycleWorkflow")
class CollectCycleWorkflow:
    @workflow.run
    async def run(self, job: CollectJob) -> dict[str, Any]:
        retry = RetryPolicy(
            initial_interval=timedelta(milliseconds=200),
            maximum_attempts=3,
            non_retryable_error_types=[SCOPE_VIOLATION_ERROR_TYPE],
        )
        scoped = await workflow.execute_activity(
            "validate_collect_job_scope",
            job,
            result_type=dict[str, Any],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry,
        )
        # Always signal the DB incident — never a caller-supplied workflow id.
        incident_id = str(scoped["incident_id"])

        raw = await workflow.execute_activity(
            "run_collect_cycle",
            job,
            result_type=dict[str, Any],
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(milliseconds=500),
                maximum_attempts=3,
            ),
        )
        updated = EvidenceUpdated(
            incident_id=incident_id,
            cycle_id=str(raw["cycle_id"]),
            evidence_ids=list(raw.get("evidence_ids") or []),
            kinds=list(raw.get("kinds") or []),
            inserted_count=int(raw.get("inserted_count") or 0),
        )

        handle = workflow.get_external_workflow_handle(incident_workflow_id(incident_id))
        try:
            await handle.signal("evidence_updated", updated)
        except Exception as exc:  # noqa: BLE001 — surface missing parent clearly
            raise ApplicationError(
                f"failed to signal IncidentWorkflow for {incident_id}: {exc}",
                type="EvidenceUpdatedSignalFailed",
                non_retryable=True,
            ) from exc

        return cast(
            dict[str, Any],
            {
                "incident_id": updated.incident_id,
                "cycle_id": updated.cycle_id,
                "evidence_ids": updated.evidence_ids,
                "kinds": updated.kinds,
                "inserted_count": updated.inserted_count,
            },
        )
