"""N18: claim ``eval.operational_pin_requested`` outbox rows and pin (GT allowed).

Runs as ``python -m incidentpilot_evaluator pin`` with ``DATABASE_URL_EVALUATOR``.
Workers never call this path — they only enqueue ``scenario_run_id``.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import UUID

import psycopg

from incidentpilot_shared.domain.outbox import (
    OutboxMessage,
    fetch_pending_outbox,
    mark_outbox_published,
    mark_outbox_retry,
    release_outbox_lease,
)
from incidentpilot_shared.eval_pin_hook import (
    EVAL_OPERATIONAL_PIN_EVENT,
    assert_eval_pin_payload,
)
from incidentpilot_shared.operational_evaluation import (
    OperationalEvalError,
    pin_operational_evaluation,
)
from incidentpilot_shared.slack_notify import SLACK_NOTIFY_EVENT

logger = logging.getLogger(__name__)


def evaluator_dsn() -> str:
    return os.environ.get(
        "DATABASE_URL_EVALUATOR",
        "postgresql://ip_evaluator:incidentpilot_evaluator@localhost:5432/incidentpilot",
    )


def connect_evaluator() -> psycopg.Connection:
    return psycopg.connect(evaluator_dsn())


def _incident_id_for_run(conn: psycopg.Connection, *, scenario_run_id: UUID) -> UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT incident_id
            FROM scenarios.scenario_run
            WHERE id = %s
            """,
            (str(scenario_run_id),),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        raise OperationalEvalError(
            f"scenario_run {scenario_run_id} missing or not linked to an incident"
        )
    return UUID(str(row[0]))


def deliver_eval_pin(message: OutboxMessage) -> dict[str, Any]:
    """Pin OperationalEvaluation for one outbox message (idempotent)."""
    if message.event_type != EVAL_OPERATIONAL_PIN_EVENT:
        raise ValueError(
            f"expected {EVAL_OPERATIONAL_PIN_EVENT}, got {message.event_type!r}"
        )
    scenario_run_id = assert_eval_pin_payload(dict(message.payload or {}))
    with connect_evaluator() as conn:
        incident_id = _incident_id_for_run(conn, scenario_run_id=scenario_run_id)
        view = pin_operational_evaluation(
            conn,
            scenario_run_id=scenario_run_id,
            incident_id=incident_id,
            commit=True,
        )
    return {
        "scenario_run_id": str(scenario_run_id),
        "incident_id": str(incident_id),
        "evaluation_id": str(view.id),
        "passed": view.passed,
        "idempotent_hit": view.idempotent_hit,
    }


def pin_once(
    *,
    limit: int = 10,
    lease_seconds: float = 15.0,
    aggregate_id: str | None = None,
) -> int:
    """Claim pending outbox; pin eval requests; release others for their owners.

    Non-eval rows (Temporal signals, Slack) are released immediately so the
    worker dispatch / notify processes can claim them. Returns published pin count.
    """
    # Claim with evaluator connection — outbox is in domain schema (granted).
    with connect_evaluator() as conn:
        messages = fetch_pending_outbox(
            conn,
            limit=limit,
            lease_seconds=lease_seconds,
            aggregate_id=aggregate_id,
        )
        conn.commit()

    published = 0
    for message in messages:
        if message.event_type != EVAL_OPERATIONAL_PIN_EVENT:
            # Leave Slack / Temporal intents for their dedicated consumers.
            with connect_evaluator() as conn:
                release_outbox_lease(conn, message.id)
                conn.commit()
            # Avoid spinning on Slack rows forever if notify is down — still OK.
            if message.event_type == SLACK_NOTIFY_EVENT:
                continue
            continue
        try:
            result = deliver_eval_pin(message)
            logger.info(
                "eval pin delivered message_id=%s evaluation_id=%s passed=%s",
                message.id,
                result.get("evaluation_id"),
                result.get("passed"),
            )
        except OperationalEvalError as exc:
            logger.warning(
                "eval pin deferred message_id=%s: %s",
                message.id,
                exc,
            )
            with connect_evaluator() as conn:
                mark_outbox_retry(
                    conn, message.id, error=str(exc), delay_seconds=5.0
                )
                conn.commit()
            continue
        except Exception as exc:
            logger.exception("eval pin error message_id=%s", message.id)
            with connect_evaluator() as conn:
                mark_outbox_retry(
                    conn, message.id, error=str(exc), delay_seconds=10.0
                )
                conn.commit()
            continue

        with connect_evaluator() as conn:
            mark_outbox_published(conn, message.id)
            conn.commit()
        published += 1
    return published
