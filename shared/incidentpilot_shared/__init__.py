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
from incidentpilot_shared.redaction import (
    EvidenceProjection,
    RedactionError,
    project_evidence_for_llm,
    supply_projection_to_llm,
)

__version__ = "0.0.0"

__all__ = [
    "AppendEvidenceResult",
    "ApprovalDecisionResult",
    "EvidenceProjection",
    "IllegalTransitionError",
    "IncidentState",
    "OutboxRequiredError",
    "RedactionError",
    "ReserveAttemptResult",
    "StaleRevisionError",
    "TransitionResult",
    "UnitOfWork",
    "__version__",
    "append_evidence_command",
    "apply_transition",
    "decide_approval_command",
    "enqueue_outbox",
    "project_evidence_for_llm",
    "reserve_execution_attempt_command",
    "supply_projection_to_llm",
    "transition_incident",
    "transition_incident_command",
    "try_begin_idempotent",
]
