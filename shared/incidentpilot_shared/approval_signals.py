"""Approval wait signal payload (I5) — Temporal-safe dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApprovalDecisionSignal:
    """Signaled to IncidentWorkflow when an Approval is decided.

    ``decision_id`` is the outbox message id (or a synthetic id in tests) for
    idempotent delivery.
    """

    decision_id: str
    approval_id: str
    action_id: str
    action_version: int
    status: str
    decided_by: str = ""
