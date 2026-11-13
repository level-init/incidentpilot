"""N18: RESOLVED → evaluator operational-pin hook.

Workers / domain commands enqueue ``eval.operational_pin_requested`` with
**only** ``scenario_run_id``. They never read GroundTruth. The evaluator
process (``ip_evaluator`` DB role) claims the outbox row and pins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from incidentpilot_shared.domain.outbox import enqueue_outbox

if TYPE_CHECKING:
    from psycopg import Connection

EVAL_OPERATIONAL_PIN_EVENT: Final[str] = "eval.operational_pin_requested"

# Payload keys allowed on the worker-side enqueue (no GT / answer fields).
_ALLOWED_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset({"scenario_run_id"})


@dataclass(frozen=True, slots=True)
class EvalPinHookResult:
    """Result of attempting the RESOLVED → eval pin join point."""

    incident_id: UUID
    scenario_run_id: UUID | None
    outbox_message_id: UUID | None
    enqueued: bool
    reason: str


def lookup_scenario_run_id_for_incident(
    conn: Connection, *, incident_id: UUID
) -> UUID | None:
    """Resolve linked ScenarioRun id — SELECT only; no GroundTruth."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM scenarios.scenario_run
            WHERE incident_id = %s
              AND status <> 'FAILED'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return UUID(str(row[0]))


def link_scenario_run_incident(
    conn: Connection,
    *,
    scenario_run_id: UUID,
    incident_id: UUID,
    commit: bool = True,
) -> None:
    """Bind ScenarioRun → incident so the RESOLVED hook can find it.

    Runner / harness writes this before validation reaches RESOLVED.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scenarios.scenario_run
            SET incident_id = %s
            WHERE id = %s
            """,
            (str(incident_id), str(scenario_run_id)),
        )
        if cur.rowcount != 1:
            raise LookupError(f"scenario_run not found: {scenario_run_id}")
    if commit:
        conn.commit()


def request_operational_evaluation_hook(
    conn: Connection,
    *,
    incident_id: UUID,
    commit: bool = False,
) -> EvalPinHookResult:
    """Enqueue evaluator pin request after incident reaches RESOLVED.

    Payload is **only** ``scenario_run_id``. No-op when the incident is not
    linked to a non-FAILED ScenarioRun (ordinary live ops).
    """
    run_id = lookup_scenario_run_id_for_incident(conn, incident_id=incident_id)
    if run_id is None:
        return EvalPinHookResult(
            incident_id=incident_id,
            scenario_run_id=None,
            outbox_message_id=None,
            enqueued=False,
            reason="no_linked_scenario_run",
        )

    payload: dict[str, Any] = {"scenario_run_id": str(run_id)}
    assert set(payload) <= _ALLOWED_PAYLOAD_KEYS

    message_id = enqueue_outbox(
        conn,
        aggregate_type="scenario_run",
        aggregate_id=str(run_id),
        event_type=EVAL_OPERATIONAL_PIN_EVENT,
        payload=payload,
    )
    if commit:
        conn.commit()
    return EvalPinHookResult(
        incident_id=incident_id,
        scenario_run_id=run_id,
        outbox_message_id=message_id,
        enqueued=True,
        reason="enqueued",
    )


def assert_eval_pin_payload(payload: dict[str, Any]) -> UUID:
    """Validate worker-emitted payload: scenario_run_id only."""
    keys = set(payload)
    if keys != _ALLOWED_PAYLOAD_KEYS:
        raise ValueError(
            f"eval pin payload must be exactly {_ALLOWED_PAYLOAD_KEYS}, got {keys}"
        )
    return UUID(str(payload["scenario_run_id"]))
