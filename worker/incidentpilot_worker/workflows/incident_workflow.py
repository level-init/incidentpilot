"""IncidentWorkflow: DETECTED → TRIAGING → INVESTIGATING (D2/D3).

Activities take expected_revision. StaleRevision is non-retryable; the workflow
re-queries Postgres and retries with a fresh revision. Optional
``wait_after_triaging`` supports crash-resume tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from incidentpilot_worker.activities.incident_transitions import (
        STALE_REVISION_ERROR_TYPE,
    )
    from incidentpilot_worker.domain_events import DomainEventEnvelope


@dataclass
class IncidentWorkflowInput:
    incident_id: str
    wait_after_triaging: bool = False
    wait_for_domain_event: bool = False


_EARLY_PATH = ("DETECTED", "TRIAGING", "INVESTIGATING")


def _rank(state: str) -> int:
    try:
        return _EARLY_PATH.index(state)
    except ValueError:
        return -1


@workflow.defn(name="IncidentWorkflow")
class IncidentWorkflow:
    def __init__(self) -> None:
        self._proceed_after_triaging = False
        self._seen_outbox_message_ids: set[str] = set()
        self._domain_event_count: int = 0
        self._last_domain_event: DomainEventEnvelope | None = None
        self._wait_for_domain_event: bool = False

    @workflow.signal
    def proceed_after_triaging(self) -> None:
        """Release the mid-triage pause (tests / operator resume)."""
        self._proceed_after_triaging = True

    @workflow.signal
    def domain_event(self, envelope: DomainEventEnvelope) -> None:
        """Idempotent outbox consumer — never applies domain transitions (D4).

        Domain state was already committed with the outbox row. Duplicate
        dispatches (at-least-once) must not double-transition.
        """
        if envelope.message_id in self._seen_outbox_message_ids:
            return
        self._seen_outbox_message_ids.add(envelope.message_id)
        self._domain_event_count += 1
        self._last_domain_event = envelope

    @workflow.query
    def domain_event_count(self) -> int:
        return self._domain_event_count

    async def _load(self, incident_id: str) -> dict[str, Any]:
        result = await workflow.execute_activity(
            "load_incident_snapshot",
            incident_id,
            result_type=dict[str, Any],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(milliseconds=200),
                maximum_attempts=5,
            ),
        )
        return cast(dict[str, Any], result)

    async def _advance_to(self, incident_id: str, to_state: str) -> None:
        """Query revision, transition; on StaleRevision re-query and retry."""
        retry = RetryPolicy(
            initial_interval=timedelta(milliseconds=100),
            maximum_attempts=1,
            non_retryable_error_types=[STALE_REVISION_ERROR_TYPE],
        )
        # Bound workflow-side re-query loops (activity itself is non-retryable on stale).
        for _ in range(8):
            snap = await self._load(incident_id)
            state = str(snap["state"])
            if state == to_state or (
                _rank(state) >= 0 and _rank(to_state) >= 0 and _rank(state) >= _rank(to_state)
            ):
                return
            revision = int(snap["revision"])
            try:
                await workflow.execute_activity(
                    "advance_incident_state",
                    args=[incident_id, to_state, revision],
                    result_type=dict[str, Any],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry,
                )
                return
            except ActivityError as exc:
                cause = exc.cause
                if isinstance(cause, ApplicationError) and cause.type == STALE_REVISION_ERROR_TYPE:
                    workflow.logger.info(
                        "StaleRevision on advance to %s; re-querying incident %s",
                        to_state,
                        incident_id,
                    )
                    continue
                raise
        raise ApplicationError(
            f"exhausted stale-revision re-queries advancing to {to_state}",
            type=STALE_REVISION_ERROR_TYPE,
            non_retryable=True,
        )

    @workflow.run
    async def run(self, input: IncidentWorkflowInput) -> str:
        self._wait_for_domain_event = input.wait_for_domain_event

        snap = await self._load(input.incident_id)
        if snap["state"] == "INVESTIGATING":
            if input.wait_for_domain_event:
                await workflow.wait_condition(lambda: self._domain_event_count > 0)
            return "INVESTIGATING"

        await self._advance_to(input.incident_id, "TRIAGING")

        if input.wait_after_triaging:
            await workflow.wait_condition(lambda: self._proceed_after_triaging)

        await self._advance_to(input.incident_id, "INVESTIGATING")

        if input.wait_for_domain_event:
            await workflow.wait_condition(lambda: self._domain_event_count > 0)

        final = await self._load(input.incident_id)
        return str(final["state"])
