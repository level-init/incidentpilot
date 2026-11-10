"""J7: validation_window activity — deterministic criteria → ValidationResult."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from temporalio import activity

from incidentpilot_shared.processors.validation import evaluate_checkout_recovery
from incidentpilot_worker.commands import record_validation_result_command
from incidentpilot_worker.db import connect


@dataclass
class ValidationWindowInput:
    incident_id: str
    execution_attempt_id: str


@activity.defn(name="handle_validation_window")
def handle_validation_window(payload: ValidationWindowInput | dict[str, Any]) -> dict[str, Any]:
    """After durable validation_window: evaluate Evidence → one ValidationResult.

    LLM is not consulted for the outcome (explain-only).
    """
    if isinstance(payload, dict):
        incident_id = str(payload["incident_id"])
        attempt_id = str(payload["execution_attempt_id"])
    else:
        incident_id = str(payload.incident_id)
        attempt_id = str(payload.execution_attempt_id)

    iid = UUID(incident_id)
    eid = UUID(attempt_id)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ea.action_id, ea.action_version
                FROM domain.execution_attempt ea
                WHERE ea.id = %s
                """,
                (attempt_id,),
            )
            attempt_row = cur.fetchone()
            action_id = UUID(str(attempt_row[0])) if attempt_row else None
            action_version = int(attempt_row[1]) if attempt_row else None

            cur.execute(
                """
                SELECT 1 FROM domain.evidence
                WHERE incident_id = %s AND kind = 'ACTION_RESULT'
                LIMIT 1
                """,
                (incident_id,),
            )
            action_result_present = cur.fetchone() is not None

            cur.execute(
                """
                SELECT id, fingerprint, payload
                FROM domain.evidence
                WHERE incident_id = %s AND kind IN ('METRIC', 'OTHER')
                ORDER BY observed_at DESC NULLS LAST, ingested_at DESC
                LIMIT 50
                """,
                (incident_id,),
            )
            metric_rows: list[dict[str, Any]] = []
            for row in cur.fetchall():
                payload_obj = row[2]
                if isinstance(payload_obj, str):
                    payload_obj = json.loads(payload_obj)
                metric_rows.append(
                    {
                        "id": str(row[0]),
                        "fingerprint": str(row[1]),
                        "payload": payload_obj if isinstance(payload_obj, dict) else {},
                    }
                )

        verdict = evaluate_checkout_recovery(
            metric_rows=metric_rows,
            action_result_present=action_result_present,
        )
        recorded = record_validation_result_command(
            conn,
            incident_id=iid,
            execution_attempt_id=eid,
            outcome=verdict.outcome,
            criteria=verdict.criteria,
            observations={
                **verdict.observations,
                "reason": verdict.reason,
            },
            action_id=action_id,
            action_version=action_version,
            provenance={
                "writer": "system",
                "source": "validation_window",
                "layer": "DETERMINISTIC_DERIVED",
                "quality_rule_id": verdict.quality_rule_id,
            },
            transition=True,
            actor="incident-workflow",
            commit=False,
        )
        conn.commit()

    return {
        "incident_id": incident_id,
        "execution_attempt_id": attempt_id,
        "validation_result_id": str(recorded.validation_result_id),
        "outcome": recorded.outcome,
        "inserted": recorded.inserted,
        "incident_state": recorded.incident_state,
        "incident_revision": recorded.incident_revision,
        "reason": verdict.reason,
        "quality_rule_id": verdict.quality_rule_id,
    }
