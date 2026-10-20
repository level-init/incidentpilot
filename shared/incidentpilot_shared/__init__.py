"""Shared domain library for IncidentPilot deployables."""

from incidentpilot_shared.domain import (
    IllegalTransitionError,
    IncidentState,
    StaleRevisionError,
    TransitionResult,
    apply_transition,
    transition_incident,
)

__version__ = "0.0.0"

__all__ = [
    "IllegalTransitionError",
    "IncidentState",
    "StaleRevisionError",
    "TransitionResult",
    "__version__",
    "apply_transition",
    "transition_incident",
]
