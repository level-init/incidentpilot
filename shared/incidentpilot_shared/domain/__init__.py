"""Shared domain command types and services."""

from incidentpilot_shared.domain.outbox import (
    OutboxRequiredError,
    UnitOfWork,
    enqueue_outbox,
    try_begin_idempotent,
)
from incidentpilot_shared.domain.transitions import (
    IllegalTransitionError,
    IncidentState,
    StaleRevisionError,
    TransitionResult,
    apply_transition,
    transition_incident,
)

__all__ = [
    "IllegalTransitionError",
    "IncidentState",
    "OutboxRequiredError",
    "StaleRevisionError",
    "TransitionResult",
    "UnitOfWork",
    "apply_transition",
    "enqueue_outbox",
    "transition_incident",
    "try_begin_idempotent",
]
