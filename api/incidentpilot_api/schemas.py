"""Pydantic models for the public OpenAPI surface (B8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "incidentpilot-api"


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    severity: str | None = None
    summary: str | None = None


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


class ActionOut(BaseModel):
    id: UUID
    incident_id: UUID
    action_type: str
    status: str
    current_version: int
    is_reversible: bool


class ApprovalOut(BaseModel):
    id: UUID
    action_id: UUID
    action_version: int
    status: str
    decided_by: str | None = None


class TimelineEventOut(BaseModel):
    id: UUID
    incident_id: UUID
    event_type: str
    summary: str
    actor: str
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class PostmortemOut(BaseModel):
    id: UUID
    incident_id: UUID
    status: str
    title: str
    body_markdown: str
    corrective_actions: list[Any]


class ImpactSnapshotOut(BaseModel):
    id: UUID
    incident_id: UUID
    captured_at: datetime
    severity: str | None = None
    customer_impact_summary: str | None = None
    estimated_affected_users: int | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


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
