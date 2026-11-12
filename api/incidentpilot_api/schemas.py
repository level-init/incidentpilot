"""Pydantic models for the public OpenAPI surface (B8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "incidentpilot-api"


class SessionOut(BaseModel):
    """Authenticated principal from Bearer (C1/C2) — used by the web shell."""

    actor_id: str
    role: str
    auth_mode: str
    email: str | None = None
    eval_entitled: bool = False


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    severity: str | None = None
    summary: str | None = None
    service_key: str | None = None


class IncidentTransition(BaseModel):
    to_state: str
    expected_revision: int = Field(ge=1)


class IncidentOut(BaseModel):
    id: UUID
    public_id: str
    state: str
    title: str
    severity: str | None
    incident_revision: int
    summary: str | None
    opened_at: datetime
    resolved_at: datetime | None
    closed_at: datetime | None
    service_keys: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)


class AlertOut(BaseModel):
    id: UUID
    fingerprint: str
    source: str
    status: str
    incident_id: UUID | None
    received_at: datetime


class EvidenceOut(BaseModel):
    id: UUID
    evidence_key: str
    incident_id: UUID
    kind: str
    summary: str
    fingerprint: str
    observed_at: datetime
    producer: str
    provenance: dict[str, Any] = Field(default_factory=dict)


class HypothesisOut(BaseModel):
    id: UUID
    incident_id: UUID
    status: str
    statement: str
    proposed_by: str
    # Column ``confidence`` stores a heuristic score (H4) — not a calibrated probability.
    confidence: float | None = None
    rank: int | None = None
    score_kind: str = "heuristic"
    provenance: dict[str, Any] = Field(default_factory=dict)
    cited_evidence_ids: list[UUID] = Field(default_factory=list)


class ActionPropose(BaseModel):
    action_type: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    target_ref: dict[str, Any] = Field(default_factory=dict)
    action_id: UUID | None = None
    hypothesis_id: UUID | None = None
    rationale: str | None = None


class ActionOut(BaseModel):
    id: UUID
    incident_id: UUID
    action_type: str
    status: str
    current_version: int
    is_reversible: bool


class ActionProposeOut(BaseModel):
    action_id: UUID
    incident_id: UUID
    action_type: str
    version: int
    current_version: int
    status: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    runbook_version_id: UUID
    allowed_action_types: list[str]
    bumped: bool
    is_reversible: bool
    reverse_action_type: str | None = None


class PolicyEvaluateBody(BaseModel):
    action_version: int | None = Field(default=None, ge=1)
    # Omit to resolve from domain.autonomy_config (I3).
    autonomy_level: int | None = Field(default=None, ge=1, le=3)


class PolicyDecisionOut(BaseModel):
    policy_decision_id: UUID
    action_id: UUID
    action_version: int
    incident_id: UUID
    decision: str
    reason: str
    policy_key: str
    policy_version: str
    action_status: str
    autonomy_level: int
    autonomy_source: str


class AutonomyConfigUpsert(BaseModel):
    autonomy_level: int = Field(ge=1, le=3)
    service_key: str | None = None
    action_type: str | None = None
    environment: str | None = None
    severity: str | None = None
    notes: str | None = None


class PolicyVersionPublish(BaseModel):
    body: dict[str, object] = Field(default_factory=dict)
    notes: str | None = None
    activate: bool = True


class PolicyVersionOut(BaseModel):
    policy_definition_id: UUID
    policy_key: str
    version: int
    version_label: str
    body: dict[str, object] = Field(default_factory=dict)
    notes: str | None = None
    created_by: str
    active: bool


class PolicyActivateOut(BaseModel):
    policy_key: str
    version: int
    version_label: str
    activated_by: str


class AutonomyConfigOut(BaseModel):
    config_id: UUID
    service_key: str | None = None
    action_type: str | None = None
    environment: str | None = None
    severity: str | None = None
    autonomy_level: int
    notes: str | None = None
    inserted: bool | None = None


class ApprovalOut(BaseModel):
    id: UUID
    action_id: UUID
    action_version: int
    status: str
    decided_by: str | None = None


class RemediationAttemptOut(BaseModel):
    id: UUID
    action_version: int
    attempt_number: int
    state: str
    error_summary: str | None = None
    reconciliation_state: str | None = None
    adapter_result: dict[str, Any] = Field(default_factory=dict)
    unsafe_to_retry: bool = False


class RemediationPolicyOut(BaseModel):
    decision: str
    reason: str | None = None
    policy_key: str | None = None
    policy_version: str | None = None


class RemediationApprovalOut(BaseModel):
    id: UUID
    action_version: int
    status: str
    decided_by: str | None = None


class RemediationActionOut(BaseModel):
    """M5 remediation card — scope visible before approve; UNKNOWN ≠ plain failed."""

    action_id: UUID
    action_type: str
    status: str
    current_version: int
    is_reversible: bool
    risk: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    target_ref: dict[str, Any] = Field(default_factory=dict)
    policy: RemediationPolicyOut | None = None
    approval: RemediationApprovalOut | None = None
    attempts: list[RemediationAttemptOut] = Field(default_factory=list)


class TimelineEventOut(BaseModel):
    id: UUID
    incident_id: UUID
    event_type: str
    summary: str
    actor: str
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditEventOut(BaseModel):
    id: UUID
    incident_id: UUID | None = None
    action: str
    actor: str
    resource_type: str
    resource_id: str | None = None
    outcome: str
    occurred_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class PostmortemOut(BaseModel):
    id: UUID
    incident_id: UUID
    status: str
    title: str
    body_markdown: str
    corrective_actions: list[Any]


class PostmortemClaimIn(BaseModel):
    text: str = Field(min_length=1)
    citations: list[Any] = Field(default_factory=list)


class PostmortemDraftCreate(BaseModel):
    """Optional explicit claims; omit to auto-generate from SoR (L4)."""

    title: str | None = Field(default=None, max_length=500)
    body_markdown: str | None = None
    claims: list[PostmortemClaimIn] | None = None


class PostmortemDraftOut(BaseModel):
    postmortem_id: UUID
    incident_id: UUID
    status: str
    title: str
    claim_count: int
    cited_evidence_ids: list[UUID]
    inserted: bool


class PostmortemFinalize(BaseModel):
    corrective_actions: list[dict[str, Any]] = Field(min_length=1)


class PostmortemFinalizeOut(BaseModel):
    postmortem_id: UUID
    incident_id: UUID
    status: str
    corrective_actions: list[dict[str, Any]]
    incident_state: str
    incident_revision: int


class PostmortemExportOut(BaseModel):
    incident_id: UUID
    postmortem_id: UUID
    public_id: str
    export_uri: str | None = None
    blob_status: str
    package: dict[str, Any]


class ImpactSnapshotOut(BaseModel):
    id: UUID
    incident_id: UUID
    captured_at: datetime
    severity: str | None = None
    customer_impact_summary: str | None = None
    estimated_affected_users: int | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ChangeOut(BaseModel):
    id: UUID
    change_key: str
    change_type: str
    service_key: str | None = None
    summary: str
    source: str
    external_ref: str | None = None
    observed_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class PinnedRunbookOut(BaseModel):
    """Pinned runbook for the incident — authority vs untrusted prose (M6/H6)."""

    pinned: bool
    runbook_key: str | None = None
    title: str | None = None
    version: int | None = None
    runbook_version_id: UUID | None = None
    allowed_action_types: list[str] = Field(default_factory=list)
    body_markdown: str | None = None
    authority_note: str = (
        "allowed_action_types is executable authority; "
        "body_markdown is untrusted human prose"
    )


class SloBurnOut(BaseModel):
    id: UUID
    incident_id: UUID
    slo_key: str
    window_label: str
    burn_rate: float | None = None
    error_budget_remaining: float | None = None
    observed_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class SeverityUpdateOut(BaseModel):
    incident_id: UUID
    previous_severity: str | None = None
    severity: str
    changed: bool
    explanation: str
    quality_rule_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class HypothesisConfirmOut(BaseModel):
    incident_id: UUID
    hypothesis_id: UUID
    status: str
    hypothesis_class: str | None = None
    caused_by_written: bool
    reason: str
    quality_rule_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
