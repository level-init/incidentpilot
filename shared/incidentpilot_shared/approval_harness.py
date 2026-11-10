"""Eval/test Approval harness (I6) — real domain decisions, no Slack.

Used by scenario/eval runners to APPROVE or REJECT while the IncidentWorkflow
waits on ``approval_decision``. Writes the same ``domain.approval`` rows as
human decide; signals Temporal so the wait resumes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from incidentpilot_shared.approval_signals import ApprovalDecisionSignal
from incidentpilot_shared.domain.commands import decide_approval_command
from incidentpilot_shared.incident_workflow import incident_workflow_id

if TYPE_CHECKING:
    from psycopg import Connection
    from temporalio.client import Client


HARNESS_ACTOR_PREFIX = "harness:"


@dataclass(frozen=True, slots=True)
class HarnessDecideResult:
    approval_id: UUID
    action_id: UUID
    action_version: int
    incident_id: UUID
    status: str
    decided_by: str
    action_status: str
    noop: bool
    workflow_signaled: bool
    signal_error: str | None = None


def harness_actor_id(raw: str = "eval") -> str:
    """Stable decided_by for harness provenance (not a forgeable client field)."""
    cleaned = str(raw).strip() or "eval"
    if cleaned.startswith(HARNESS_ACTOR_PREFIX):
        return cleaned
    return f"{HARNESS_ACTOR_PREFIX}{cleaned}"


def load_approval_for_harness(
    conn: Connection,
    *,
    approval_id: UUID,
) -> dict[str, Any]:
    """Load approval + policy + incident for harness decide."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.action_id, a.action_version, a.status,
                   act.incident_id, pd.decision AS policy_decision
            FROM domain.approval a
            JOIN domain.action act ON act.id = a.action_id
            LEFT JOIN domain.policy_decision pd
              ON pd.action_id = a.action_id
             AND pd.action_version = a.action_version
            WHERE a.id = %s
            """,
            (str(approval_id),),
        )
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"approval {approval_id} not found")
    return {
        "approval_id": UUID(str(row[0])),
        "action_id": UUID(str(row[1])),
        "action_version": int(row[2]),
        "approval_status": str(row[3]),
        "incident_id": UUID(str(row[4])),
        "policy_decision": None if row[5] is None else str(row[5]),
    }


async def signal_approval_decision(
    client: Client,
    *,
    incident_id: UUID | str,
    signal: ApprovalDecisionSignal,
) -> None:
    """Wake IncidentWorkflow approval wait (idempotent by decision_id)."""
    handle = client.get_workflow_handle(incident_workflow_id(incident_id))
    await handle.signal("approval_decision", signal)


async def harness_decide_approval(
    conn: Connection,
    *,
    approval_id: UUID,
    status: str,
    decided_by: str = "eval",
    temporal_client: Client | None = None,
    commit: bool = True,
) -> HarnessDecideResult:
    """Write a real ApprovalDecision and optionally signal the workflow.

    ``status`` must be APPROVED or REJECTED. Policy must be REQUIRE_APPROVAL
    (BLOCK is absolute). When ``temporal_client`` is set, signals immediately
    so the wait resumes without waiting for the outbox dispatcher.
    """
    if status not in {"APPROVED", "REJECTED"}:
        raise ValueError("status must be APPROVED or REJECTED")

    row = load_approval_for_harness(conn, approval_id=approval_id)
    policy = row["policy_decision"]
    if policy == "BLOCK":
        raise PermissionError("PolicyDecision is BLOCK; harness approval is forbidden")
    if policy != "REQUIRE_APPROVAL":
        raise PermissionError("no REQUIRE_APPROVAL PolicyDecision for this action version")

    actor = harness_actor_id(decided_by)
    decided = decide_approval_command(
        conn,
        action_id=row["action_id"],
        action_version=row["action_version"],
        status=status,
        decided_by=actor,
        commit=commit,
    )

    signaled = False
    signal_error: str | None = None
    if temporal_client is not None and not decided.noop:
        signal = ApprovalDecisionSignal(
            decision_id=f"harness:{decided.approval_id}:{status}:{uuid4().hex[:8]}",
            approval_id=str(decided.approval_id),
            action_id=str(decided.action_id),
            action_version=decided.action_version,
            status=status,
            decided_by=actor,
        )
        try:
            await signal_approval_decision(
                temporal_client,
                incident_id=row["incident_id"],
                signal=signal,
            )
            signaled = True
        except Exception as exc:  # noqa: BLE001 — surface to caller/API
            signal_error = str(exc)

    return HarnessDecideResult(
        approval_id=decided.approval_id,
        action_id=decided.action_id,
        action_version=decided.action_version,
        incident_id=row["incident_id"],
        status=decided.status,
        decided_by=actor,
        action_status=decided.action_status,
        noop=decided.noop,
        workflow_signaled=signaled,
        signal_error=signal_error,
    )
