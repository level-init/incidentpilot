"""Durable timer names + defaults for IncidentWorkflow (D5).

Approval timeout is wired in IncidentWorkflow (I5); validation_window in J7.
Durations are seconds (JSON-safe for Temporal payloads).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

TIMER_INVESTIGATION_DEADLINE: Final[str] = "investigation_deadline"
TIMER_APPROVAL_TIMEOUT: Final[str] = "approval_timeout"
TIMER_VALIDATION_WINDOW: Final[str] = "validation_window"

ALL_TIMER_NAMES: Final[tuple[str, ...]] = (
    TIMER_INVESTIGATION_DEADLINE,
    TIMER_APPROVAL_TIMEOUT,
    TIMER_VALIDATION_WINDOW,
)


@dataclass(frozen=True, slots=True)
class WorkflowTimerConfig:
    """Durations (seconds) for the three closed-loop waits."""

    investigation_deadline_seconds: float = 4 * 3600
    approval_timeout_seconds: float = 30 * 60
    validation_window_seconds: float = 15 * 60

    def as_named_delays(self) -> tuple[tuple[str, timedelta], ...]:
        return (
            (
                TIMER_INVESTIGATION_DEADLINE,
                timedelta(seconds=self.investigation_deadline_seconds),
            ),
            (
                TIMER_APPROVAL_TIMEOUT,
                timedelta(seconds=self.approval_timeout_seconds),
            ),
            (
                TIMER_VALIDATION_WINDOW,
                timedelta(seconds=self.validation_window_seconds),
            ),
        )
