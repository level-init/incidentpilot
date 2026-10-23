"""IncidentWorkflow: DETECTED → TRIAGING → INVESTIGATING (D2).

Re-reads Postgres inside activities before each TransitionIncident. Optional
``wait_after_triaging`` pause supports crash-resume verification (kill worker
mid-triage, restart, signal proceed).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from incidentpilot_worker.activities.incident_transitions import (
        advance_incident_state,
        load_incident_snapshot,
    )


@dataclass
class IncidentWorkflowInput:
    incident_id: str
    wait_after_triaging: bool = False


@workflow.defn(name="IncidentWorkflow")
class IncidentWorkflow:
    def __init__(self) -> None:
        self._proceed_after_triaging = False

    @workflow.signal
    def proceed_after_triaging(self) -> None:
        """Release the mid-triage pause (tests / operator resume)."""
        self._proceed_after_triaging = True

    @workflow.run
    async def run(self, input: IncidentWorkflowInput) -> str:
        retry = RetryPolicy(
            initial_interval=timedelta(milliseconds=200),
            maximum_attempts=5,
        )
        timeout = timedelta(seconds=30)

        snap = await workflow.execute_activity(
            load_incident_snapshot,
            input.incident_id,
            start_to_close_timeout=timeout,
            retry_policy=retry,
        )
        if snap["state"] == "INVESTIGATING":
            return "INVESTIGATING"

        await workflow.execute_activity(
            advance_incident_state,
            args=[input.incident_id, "TRIAGING"],
            start_to_close_timeout=timeout,
            retry_policy=retry,
        )

        if input.wait_after_triaging:
            await workflow.wait_condition(lambda: self._proceed_after_triaging)

        await workflow.execute_activity(
            advance_incident_state,
            args=[input.incident_id, "INVESTIGATING"],
            start_to_close_timeout=timeout,
            retry_policy=retry,
        )

        final = await workflow.execute_activity(
            load_incident_snapshot,
            input.incident_id,
            start_to_close_timeout=timeout,
            retry_policy=retry,
        )
        return str(final["state"])
