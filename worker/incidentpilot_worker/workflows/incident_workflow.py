"""IncidentWorkflow: DETECTED → TRIAGING → INVESTIGATING (+ durable timers).

D2/D3: transition activities with expected_revision / StaleRevision re-query.
D4: idempotent domain_event signals from the outbox dispatcher.
D5: investigation / approval / validation durable timers (handlers stubbed).
G6: idempotent EvidenceUpdated signals from CollectCycleWorkflow.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, cast

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from incidentpilot_shared.collect_job import EvidenceUpdated
    from incidentpilot_shared.incident_workflow import IncidentWorkflowInput
    from incidentpilot_worker.activities.incident_transitions import (
        STALE_REVISION_ERROR_TYPE,
    )
    from incidentpilot_worker.domain_events import DomainEventEnvelope
    from incidentpilot_worker.workflows.timers import (
        ALL_TIMER_NAMES,
        WorkflowTimerConfig,
    )

# Re-export for existing ``from ...incident_workflow import IncidentWorkflowInput``.
__all__ = ["IncidentWorkflow", "IncidentWorkflowInput"]


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
        self._seen_evidence_cycle_ids: set[str] = set()
        self._evidence_updated_count: int = 0
        self._last_evidence_updated: EvidenceUpdated | None = None
        self._wait_for_evidence_updated: bool = False
        self._timers_armed: list[str] = []
        self._timer_fire_counts: dict[str, int] = {name: 0 for name in ALL_TIMER_NAMES}

    @workflow.signal
    def proceed_after_triaging(self) -> None:
        """Release the mid-triage pause (tests / operator resume)."""
        self._proceed_after_triaging = True

    @workflow.signal
    def domain_event(self, envelope: DomainEventEnvelope) -> None:
        """Idempotent outbox consumer — never applies domain transitions (D4)."""
        if envelope.message_id in self._seen_outbox_message_ids:
            return
        self._seen_outbox_message_ids.add(envelope.message_id)
        self._domain_event_count += 1
        self._last_domain_event = envelope

    @workflow.signal
    def evidence_updated(self, update: EvidenceUpdated) -> None:
        """Idempotent collect-cycle completion (G6) — dedupe by cycle_id."""
        if update.cycle_id in self._seen_evidence_cycle_ids:
            return
        self._seen_evidence_cycle_ids.add(update.cycle_id)
        self._evidence_updated_count += 1
        self._last_evidence_updated = update

    @workflow.query
    def domain_event_count(self) -> int:
        return self._domain_event_count

    @workflow.query
    def evidence_updated_count(self) -> int:
        return self._evidence_updated_count

    @workflow.query
    def last_evidence_updated(self) -> EvidenceUpdated | None:
        return self._last_evidence_updated

    @workflow.query
    def timers_armed(self) -> list[str]:
        return list(self._timers_armed)

    @workflow.query
    def timer_fire_count(self, name: str) -> int:
        return int(self._timer_fire_counts.get(name, 0))

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

    async def _fire_timer(self, name: str, delay: timedelta) -> None:
        """Durable sleep then stub handler — survives worker death (D5)."""
        if name not in self._timers_armed:
            self._timers_armed.append(name)
        await workflow.sleep(delay)
        self._timer_fire_counts[name] = self._timer_fire_counts.get(name, 0) + 1
        workflow.logger.info("durable timer fired: %s (stub handler)", name)

    async def _arm_timers(self, config: WorkflowTimerConfig) -> None:
        await asyncio.gather(
            *[self._fire_timer(name, delay) for name, delay in config.as_named_delays()]
        )

    @workflow.run
    async def run(self, input: IncidentWorkflowInput) -> str:
        self._wait_for_domain_event = input.wait_for_domain_event
        self._wait_for_evidence_updated = input.wait_for_evidence_updated

        snap = await self._load(input.incident_id)
        if snap["state"] != "INVESTIGATING":
            await self._advance_to(input.incident_id, "TRIAGING")

            if input.wait_after_triaging:
                await workflow.wait_condition(lambda: self._proceed_after_triaging)

            await self._advance_to(input.incident_id, "INVESTIGATING")

        if input.wait_for_domain_event:
            await workflow.wait_condition(lambda: self._domain_event_count > 0)

        # G10: natural path kicks collect on evidence queue (by activity name — no
        # CollectCycleWorkflow import on general / no Prom/Loki/Tempo).
        if input.start_collect_cycle:
            await workflow.execute_activity(
                "kickoff_collect_cycle",
                input.incident_id,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(milliseconds=200),
                    maximum_attempts=3,
                ),
            )

        if input.wait_for_evidence_updated:
            await workflow.wait_condition(lambda: self._evidence_updated_count > 0)

        if input.timers is not None:
            if input.wait_for_timer is not None:
                # Arm all timers in background; wait for the named one (kill-resume).
                for name, delay in input.timers.as_named_delays():
                    asyncio.create_task(self._fire_timer(name, delay))
                wait_name = input.wait_for_timer
                await workflow.wait_condition(
                    lambda: self._timer_fire_counts.get(wait_name, 0) >= 1
                )
            else:
                await self._arm_timers(input.timers)

        final = await self._load(input.incident_id)
        return str(final["state"])
