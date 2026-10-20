"""Shared domain command types and services."""

from incidentpilot_shared.domain.commands import (
    AppendEvidenceResult,
    ApprovalDecisionResult,
    ReserveAttemptResult,
    append_evidence_command,
    decide_approval_command,
    reserve_execution_attempt_command,
    transition_incident_command,
)
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
    "AppendEvidenceResult",
    "ApprovalDecisionResult",
    "IllegalTransitionError",
    "IncidentState",
    "OutboxRequiredError",
    "ReserveAttemptResult",
    "StaleRevisionError",
    "TransitionResult",
    "UnitOfWork",
    "append_evidence_command",
    "apply_transition",
    "decide_approval_command",
    "enqueue_outbox",
    "reserve_execution_attempt_command",
    "transition_incident",
    "transition_incident_command",
    "try_begin_idempotent",
]
