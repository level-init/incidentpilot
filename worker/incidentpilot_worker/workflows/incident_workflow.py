"""IncidentWorkflow: DETECTED → TRIAGING → INVESTIGATING (+ durable timers).

D2/D3: transition activities with expected_revision / StaleRevision re-query.
D4: idempotent domain_event signals from the outbox dispatcher.
D5: investigation / approval / validation durable timers.
G6: idempotent EvidenceUpdated signals from CollectCycleWorkflow.
I5: AWAITING_APPROVAL wait — signal vs approval_timeout; timeout never executes.
J7: VALIDATING wait — durable validation_window → ValidationResult (one per attempt).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, cast

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from incidentpilot_shared.approval_signals import ApprovalDecisionSignal
    from incidentpilot_shared.collect_job import EvidenceUpdated
    from incidentpilot_shared.incident_workflow import IncidentWorkflowInput
    from incidentpilot_worker.activities.incident_transitions import (
        STALE_REVISION_ERROR_TYPE,
    )
    from incidentpilot_worker.domain_events import DomainEventEnvelope
    from incidentpilot_worker.workflows.timers import (
        ALL_TIMER_NAMES,
        TIMER_APPROVAL_TIMEOUT,
        TIMER_VALIDATION_WINDOW,
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
        # I5 approval wait
        self._seen_approval_decision_ids: set[str] = set()
        self._approval_outcome: str | None = None
        self._last_approval_decision: ApprovalDecisionSignal | None = None
        self._approval_timed_out: bool = False
        self._approval_wait_result: str | None = None
        self._remediation_executed: bool = False
        # J7 validation window
        self._validation_outcome: str | None = None
        self._validation_result_id: str | None = None

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

    @workflow.signal
    def approval_decision(self, decision: ApprovalDecisionSignal) -> None:
        """Idempotent approval decide wake-up (I5). Does not execute remediation."""
        if decision.decision_id in self._seen_approval_decision_ids:
            return
        self._seen_approval_decision_ids.add(decision.decision_id)
        if decision.status not in {"APPROVED", "REJECTED"}:
            workflow.logger.warning(
                "ignoring approval_decision with status=%s", decision.status
            )
            return
        # First decisive signal wins; later duplicates ignored above.
        if self._approval_outcome is None:
            self._approval_outcome = decision.status
            self._last_approval_decision = decision

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

    @workflow.query
    def approval_wait_result(self) -> str | None:
        """APPROVED | REJECTED | TIMEOUT once the wait completes."""
        return self._approval_wait_result

    @workflow.query
    def remediation_executed(self) -> bool:
        """I5 guarantee: approval timeout never flips this true."""
        return self._remediation_executed

    @workflow.query
    def validation_outcome(self) -> str | None:
        """J7 ValidationResult outcome after validation_window."""
        return self._validation_outcome

    @workflow.query
    def validation_result_id(self) -> str | None:
        return self._validation_result_id

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

    @staticmethod
    def _coerce_timer_config(raw: Any) -> WorkflowTimerConfig | None:
        """Payload converter may deliver timers as a plain dict (shared ``Any``)."""
        if raw is None:
            return None
        if isinstance(raw, WorkflowTimerConfig):
            return raw
        if isinstance(raw, dict):
            return WorkflowTimerConfig(
                investigation_deadline_seconds=float(
                    raw.get("investigation_deadline_seconds", 4 * 3600)
                ),
                approval_timeout_seconds=float(
                    raw.get("approval_timeout_seconds", 30 * 60)
                ),
                validation_window_seconds=float(
                    raw.get("validation_window_seconds", 15 * 60)
                ),
            )
        # Duck-typed (e.g. SimpleNamespace from converter).
        return WorkflowTimerConfig(
            investigation_deadline_seconds=float(
                getattr(raw, "investigation_deadline_seconds", 4 * 3600)
            ),
            approval_timeout_seconds=float(
                getattr(raw, "approval_timeout_seconds", 30 * 60)
            ),
            validation_window_seconds=float(
                getattr(raw, "validation_window_seconds", 15 * 60)
            ),
        )

    async def _wait_approval_or_timeout(self, timeout: timedelta) -> str:
        """Race approval_decision signal vs durable approval_timeout (I5).

        Uses ``wait_condition(..., timeout=)`` so Temporal creates a real timer
        (time-skipping + worker-kill resume).
        """
        if TIMER_APPROVAL_TIMEOUT not in self._timers_armed:
            self._timers_armed.append(TIMER_APPROVAL_TIMEOUT)
        try:
            await workflow.wait_condition(
                lambda: self._approval_outcome is not None,
                timeout=timeout,
                timeout_summary=TIMER_APPROVAL_TIMEOUT,
            )
        except TimeoutError:
            self._approval_timed_out = True
            self._timer_fire_counts[TIMER_APPROVAL_TIMEOUT] = (
                self._timer_fire_counts.get(TIMER_APPROVAL_TIMEOUT, 0) + 1
            )
            workflow.logger.info(
                "durable timer fired: %s (I5 approval wait)",
                TIMER_APPROVAL_TIMEOUT,
            )
            return "TIMEOUT"
        assert self._approval_outcome is not None
        return self._approval_outcome

    async def _on_approval_timeout(self, incident_id: str) -> None:
        """Expire pending approvals + replan; never set remediation_executed."""
        result = await workflow.execute_activity(
            "handle_approval_timeout",
            incident_id,
            result_type=dict[str, Any],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(milliseconds=200),
                maximum_attempts=5,
                non_retryable_error_types=[STALE_REVISION_ERROR_TYPE],
            ),
        )
        if result.get("remediation_executed"):
            # Defense in depth — activity contract forbids this.
            raise ApplicationError(
                "approval timeout must not execute remediation",
                type="ApprovalTimeoutExecuted",
                non_retryable=True,
            )
        self._remediation_executed = False

    async def _on_approval_rejected(self, incident_id: str) -> None:
        """I6: reject → replan; never execute remediation."""
        result = await workflow.execute_activity(
            "handle_approval_rejected",
            incident_id,
            result_type=dict[str, Any],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(milliseconds=200),
                maximum_attempts=5,
                non_retryable_error_types=[STALE_REVISION_ERROR_TYPE],
            ),
        )
        if result.get("remediation_executed"):
            raise ApplicationError(
                "approval reject must not execute remediation",
                type="ApprovalRejectExecuted",
                non_retryable=True,
            )
        self._remediation_executed = False

    async def _wait_validation_window(self, timeout: timedelta) -> None:
        """Durable validation_window sleep — survives worker kill (J7)."""
        if TIMER_VALIDATION_WINDOW not in self._timers_armed:
            self._timers_armed.append(TIMER_VALIDATION_WINDOW)
        await workflow.sleep(timeout)
        self._timer_fire_counts[TIMER_VALIDATION_WINDOW] = (
            self._timer_fire_counts.get(TIMER_VALIDATION_WINDOW, 0) + 1
        )
        workflow.logger.info(
            "durable timer fired: %s (J7 validation window)",
            TIMER_VALIDATION_WINDOW,
        )

    async def _on_validation_window(
        self, incident_id: str, execution_attempt_id: str
    ) -> None:
        result = await workflow.execute_activity(
            "handle_validation_window",
            {"incident_id": incident_id, "execution_attempt_id": execution_attempt_id},
            result_type=dict[str, Any],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(milliseconds=200),
                maximum_attempts=5,
                non_retryable_error_types=[STALE_REVISION_ERROR_TYPE],
            ),
        )
        self._validation_outcome = str(result.get("outcome") or "")
        self._validation_result_id = (
            str(result["validation_result_id"])
            if result.get("validation_result_id")
            else None
        )

    @workflow.run
    async def run(self, input: IncidentWorkflowInput) -> str:
        self._wait_for_domain_event = input.wait_for_domain_event
        self._wait_for_evidence_updated = input.wait_for_evidence_updated

        snap = await self._load(input.incident_id)
        state = str(snap["state"])
        # Only drive the early DETECTED→…→INVESTIGATING path when still early.
        # Later states (DIAGNOSED / AWAITING_APPROVAL / …) must not be rewound.
        if state in {"DETECTED", "TRIAGING"}:
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

        timer_config = self._coerce_timer_config(input.timers)

        if (
            timer_config is not None
            and not input.wait_for_approval
            and not input.wait_for_validation
        ):
            if input.wait_for_timer is not None:
                # Arm all timers in background; wait for the named one (kill-resume).
                for name, delay in timer_config.as_named_delays():
                    asyncio.create_task(self._fire_timer(name, delay))
                wait_name = input.wait_for_timer
                await workflow.wait_condition(
                    lambda: self._timer_fire_counts.get(wait_name, 0) >= 1
                )
            else:
                await self._arm_timers(timer_config)

        if input.wait_for_approval:
            timeout_seconds = (
                float(timer_config.approval_timeout_seconds)
                if timer_config is not None
                else 30 * 60.0
            )
            outcome = await self._wait_approval_or_timeout(
                timedelta(seconds=timeout_seconds)
            )
            self._approval_wait_result = outcome
            if outcome == "TIMEOUT":
                await self._on_approval_timeout(input.incident_id)
            elif outcome == "REJECTED":
                # I6: reject → replan (DIAGNOSED); never execute.
                await self._on_approval_rejected(input.incident_id)
            # APPROVED: domain decided; remediation execute is Epic J.

        if input.wait_for_validation:
            if not input.execution_attempt_id:
                raise ApplicationError(
                    "wait_for_validation requires execution_attempt_id",
                    type="ValidationAttemptRequired",
                    non_retryable=True,
                )
            timeout_seconds = (
                float(timer_config.validation_window_seconds)
                if timer_config is not None
                else 15 * 60.0
            )
            await self._wait_validation_window(timedelta(seconds=timeout_seconds))
            await self._on_validation_window(
                input.incident_id, str(input.execution_attempt_id)
            )

        final = await self._load(input.incident_id)
        return str(final["state"])
