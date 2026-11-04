"""Shared domain command types and services."""

from incidentpilot_shared.domain.commands import (
    AppendEvidenceResult,
    ApprovalDecisionResult,
    ReserveAttemptResult,
    UpsertAlertResult,
    append_evidence_command,
    decide_approval_command,
    reserve_execution_attempt_command,
    transition_incident_command,
    upsert_alert_command,
)
from incidentpilot_shared.domain.outbox import (
    OutboxMessage,
    OutboxRequiredError,
    UnitOfWork,
    enqueue_outbox,
    fetch_pending_outbox,
    mark_outbox_published,
    mark_outbox_retry,
    release_outbox_lease,
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
    "OutboxMessage",
    "OutboxRequiredError",
    "ReserveAttemptResult",
    "StaleRevisionError",
    "TransitionResult",
    "UnitOfWork",
    "UpsertAlertResult",
    "append_evidence_command",
    "apply_transition",
    "decide_approval_command",
    "enqueue_outbox",
    "fetch_pending_outbox",
    "mark_outbox_published",
    "mark_outbox_retry",
    "release_outbox_lease",
    "reserve_execution_attempt_command",
    "transition_incident",
    "transition_incident_command",
    "try_begin_idempotent",
    "upsert_alert_command",
]
