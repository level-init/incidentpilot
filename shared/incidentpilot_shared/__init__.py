"""Shared domain library for IncidentPilot deployables."""

from incidentpilot_shared.domain import (
    AppendEvidenceResult,
    ApprovalDecisionResult,
    IllegalTransitionError,
    IncidentState,
    OutboxRequiredError,
    ReserveAttemptResult,
    StaleRevisionError,
    TransitionResult,
    UnitOfWork,
    append_evidence_command,
    apply_transition,
    decide_approval_command,
    enqueue_outbox,
    reserve_execution_attempt_command,
    transition_incident,
    transition_incident_command,
    try_begin_idempotent,
)

__version__ = "0.0.0"

__all__ = [
    "AppendEvidenceResult",
    "ApprovalDecisionResult",
    "IllegalTransitionError",
    "IncidentState",
    "OutboxRequiredError",
    "ReserveAttemptResult",
    "StaleRevisionError",
    "TransitionResult",
    "UnitOfWork",
    "__version__",
    "append_evidence_command",
    "apply_transition",
    "decide_approval_command",
    "enqueue_outbox",
    "reserve_execution_attempt_command",
    "transition_incident",
    "transition_incident_command",
    "try_begin_idempotent",
]
