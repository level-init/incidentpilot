"""Shared domain library for IncidentPilot deployables."""

from incidentpilot_shared.domain import (
    IllegalTransitionError,
    IncidentState,
    OutboxRequiredError,
    StaleRevisionError,
    TransitionResult,
    UnitOfWork,
    apply_transition,
    enqueue_outbox,
    transition_incident,
    try_begin_idempotent,
)

__version__ = "0.0.0"

__all__ = [
    "IllegalTransitionError",
    "IncidentState",
    "OutboxRequiredError",
    "StaleRevisionError",
    "TransitionResult",
    "UnitOfWork",
    "__version__",
    "apply_transition",
    "enqueue_outbox",
    "transition_incident",
    "try_begin_idempotent",
]
