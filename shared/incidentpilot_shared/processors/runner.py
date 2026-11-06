"""Apply deterministic processors to parent Evidence rows (G4)."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from incidentpilot_shared.domain.commands import (
    AppendEvidenceResult,
    append_derived_evidence_command,
)
from incidentpilot_shared.processors.baseline import RULE_BASELINE_COMPARE, baseline_compare
from incidentpilot_shared.processors.top_errors import RULE_TOP_ERRORS, top_errors

if TYPE_CHECKING:
    from psycopg import Connection


def _fp(rule_id: str, parent_id: UUID, body: dict[str, Any]) -> str:
    material = json.dumps(
        {"rule": rule_id, "parent": str(parent_id), "body": body},
        sort_keys=True,
    )
    digest = hashlib.sha256(material.encode()).hexdigest()[:24]
    return f"deterministic_processor:{rule_id}:{digest}"


def process_metric_baseline(
    conn: Connection,
    *,
    incident_id: UUID,
    parent_evidence_id: UUID,
    metric_payload: dict[str, Any],
    threshold_ratio: float = 2.0,
    commit: bool = True,
) -> AppendEvidenceResult | None:
    derived = baseline_compare(metric_payload, threshold_ratio=threshold_ratio)
    if derived is None:
        return None
    return append_derived_evidence_command(
        conn,
        incident_id=incident_id,
        kind=derived.kind,
        fingerprint=_fp(RULE_BASELINE_COMPARE, parent_evidence_id, derived.payload),
        summary=derived.summary,
        quality_rule_id=derived.quality_rule_id,
        parent_evidence_ids=[parent_evidence_id],
        payload=derived.payload,
        commit=commit,
    )


def process_log_top_errors(
    conn: Connection,
    *,
    incident_id: UUID,
    parent_evidence_id: UUID,
    log_payload: dict[str, Any],
    limit: int = 5,
    commit: bool = True,
) -> AppendEvidenceResult | None:
    derived = top_errors(log_payload, limit=limit)
    if derived is None:
        return None
    return append_derived_evidence_command(
        conn,
        incident_id=incident_id,
        kind=derived.kind,
        fingerprint=_fp(RULE_TOP_ERRORS, parent_evidence_id, derived.payload),
        summary=derived.summary,
        quality_rule_id=derived.quality_rule_id,
        parent_evidence_ids=[parent_evidence_id],
        payload=derived.payload,
        commit=commit,
    )
