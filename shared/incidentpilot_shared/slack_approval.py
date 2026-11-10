"""Map Slack interactive approve/reject → ApprovalDecision (K3).

Button ``value`` JSON binds ``approval_id`` + ``action_id`` + ``action_version``.
Mismatched version → visible ``STALE_ACTION_VERSION`` (no domain decide).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from incidentpilot_shared.approval_signals import ApprovalDecisionSignal
from incidentpilot_shared.domain.commands import (
    StaleActionVersion,
    decide_approval_command,
)
from incidentpilot_shared.incident_workflow import incident_workflow_id

if TYPE_CHECKING:
    from psycopg import Connection
    from temporalio.client import Client

SLACK_ACTOR_PREFIX = "slack:"
STALE_CODE = "STALE_ACTION_VERSION"

DecisionStatus = Literal["APPROVED", "REJECTED"]


@dataclass(frozen=True, slots=True)
class SlackApprovalIntent:
    approval_id: UUID
    action_id: UUID
    action_version: int
    decision: DecisionStatus


@dataclass(frozen=True, slots=True)
class SlackApprovalMapResult:
    ok: bool
    visible_message: str
    code: str | None
    approval_id: UUID | None
    action_id: UUID | None
    action_version: int | None
    decision: str | None
    incident_id: UUID | None
    workflow_signaled: bool
    interaction_status: str
    noop: bool = False


def slack_actor_id(slack_user_id: str | None) -> str:
    raw = (slack_user_id or "unknown").strip() or "unknown"
    if raw.startswith(SLACK_ACTOR_PREFIX):
        return raw
    return f"{SLACK_ACTOR_PREFIX}{raw}"


def encode_slack_approval_value(
    *,
    approval_id: UUID | str,
    action_id: UUID | str,
    action_version: int,
    decision: DecisionStatus,
) -> str:
    """Serialize button ``value`` for Slack Block Kit approve/reject actions."""
    return json.dumps(
        {
            "approval_id": str(approval_id),
            "action_id": str(action_id),
            "action_version": int(action_version),
            "decision": decision,
        },
        separators=(",", ":"),
    )


def parse_slack_approval_intent(payload: dict[str, Any]) -> SlackApprovalIntent | None:
    """Extract approve/reject intent from a Slack ``block_actions`` payload."""
    if str(payload.get("type") or "") != "block_actions":
        return None
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        return None
    action = actions[0]
    if not isinstance(action, dict):
        return None

    action_name = str(action.get("action_id") or "")
    raw_value = action.get("value")
    data: dict[str, Any]
    if isinstance(raw_value, str) and raw_value.strip().startswith("{"):
        parsed = json.loads(raw_value)
        if not isinstance(parsed, dict):
            return None
        data = parsed
    elif isinstance(raw_value, dict):
        data = raw_value
    else:
        return None

    decision_raw = str(data.get("decision") or "").upper()
    if not decision_raw:
        if action_name in {"ip_approve", "approve"}:
            decision_raw = "APPROVED"
        elif action_name in {"ip_reject", "reject"}:
            decision_raw = "REJECTED"
        else:
            return None
    if decision_raw not in {"APPROVED", "REJECTED"}:
        return None

    try:
        return SlackApprovalIntent(
            approval_id=UUID(str(data["approval_id"])),
            action_id=UUID(str(data["action_id"])),
            action_version=int(data["action_version"]),
            decision=decision_raw,  # type: ignore[arg-type]
        )
    except (KeyError, ValueError, TypeError):
        return None


def _mark_interaction(
    conn: Connection,
    *,
    interaction_id: UUID,
    status: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE domain.slack_interaction
            SET status = %s
            WHERE id = %s
            """,
            (status, str(interaction_id)),
        )


def _load_approval(conn: Connection, approval_id: UUID) -> dict[str, Any]:
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


async def map_slack_interaction_to_approval(
    conn: Connection,
    *,
    interaction_id: UUID,
    payload: dict[str, Any],
    temporal_client: Client | None = None,
    commit: bool = True,
) -> SlackApprovalMapResult:
    """Decide approval from a verified Slack payload; signal workflow when possible."""
    intent = parse_slack_approval_intent(payload)
    if intent is None:
        _mark_interaction(conn, interaction_id=interaction_id, status="RECEIVED")
        if commit:
            conn.commit()
        return SlackApprovalMapResult(
            ok=True,
            visible_message="Interaction recorded (not an approve/reject action).",
            code=None,
            approval_id=None,
            action_id=None,
            action_version=None,
            decision=None,
            incident_id=None,
            workflow_signaled=False,
            interaction_status="RECEIVED",
        )

    try:
        row = _load_approval(conn, intent.approval_id)
    except LookupError:
        _mark_interaction(conn, interaction_id=interaction_id, status="FAILED")
        if commit:
            conn.commit()
        return SlackApprovalMapResult(
            ok=False,
            visible_message="Approval not found for this Slack action.",
            code="APPROVAL_NOT_FOUND",
            approval_id=intent.approval_id,
            action_id=intent.action_id,
            action_version=intent.action_version,
            decision=intent.decision,
            incident_id=None,
            workflow_signaled=False,
            interaction_status="FAILED",
        )

    if row["action_id"] != intent.action_id or row["action_version"] != intent.action_version:
        msg = (
            f"{STALE_CODE}: Slack button bound action "
            f"{intent.action_id} v{intent.action_version}, "
            f"current approval is {row['action_id']} v{row['action_version']}"
        )
        _mark_interaction(conn, interaction_id=interaction_id, status="FAILED")
        if commit:
            conn.commit()
        return SlackApprovalMapResult(
            ok=False,
            visible_message=msg,
            code=STALE_CODE,
            approval_id=intent.approval_id,
            action_id=intent.action_id,
            action_version=intent.action_version,
            decision=intent.decision,
            incident_id=row["incident_id"],
            workflow_signaled=False,
            interaction_status="FAILED",
        )

    policy = row["policy_decision"]
    if policy == "BLOCK":
        _mark_interaction(conn, interaction_id=interaction_id, status="FAILED")
        if commit:
            conn.commit()
        return SlackApprovalMapResult(
            ok=False,
            visible_message="PolicyDecision is BLOCK; Slack approval forbidden.",
            code="POLICY_BLOCK",
            approval_id=intent.approval_id,
            action_id=intent.action_id,
            action_version=intent.action_version,
            decision=intent.decision,
            incident_id=row["incident_id"],
            workflow_signaled=False,
            interaction_status="FAILED",
        )
    if policy != "REQUIRE_APPROVAL":
        _mark_interaction(conn, interaction_id=interaction_id, status="FAILED")
        if commit:
            conn.commit()
        return SlackApprovalMapResult(
            ok=False,
            visible_message="No REQUIRE_APPROVAL PolicyDecision for this action version.",
            code="POLICY_REQUIRED",
            approval_id=intent.approval_id,
            action_id=intent.action_id,
            action_version=intent.action_version,
            decision=intent.decision,
            incident_id=row["incident_id"],
            workflow_signaled=False,
            interaction_status="FAILED",
        )

    user = None
    user_obj = payload.get("user")
    if isinstance(user_obj, dict):
        user = user_obj.get("id") or user_obj.get("username")
    actor = slack_actor_id(str(user) if user else None)

    try:
        decided = decide_approval_command(
            conn,
            action_id=intent.action_id,
            action_version=intent.action_version,
            status=intent.decision,
            decided_by=actor,
            commit=False,
        )
    except (LookupError, StaleActionVersion) as exc:
        _mark_interaction(conn, interaction_id=interaction_id, status="FAILED")
        if commit:
            conn.commit()
        code = getattr(exc, "code", None) or STALE_CODE
        return SlackApprovalMapResult(
            ok=False,
            visible_message=str(exc),
            code=str(code),
            approval_id=intent.approval_id,
            action_id=intent.action_id,
            action_version=intent.action_version,
            decision=intent.decision,
            incident_id=row["incident_id"],
            workflow_signaled=False,
            interaction_status="FAILED",
        )

    _mark_interaction(conn, interaction_id=interaction_id, status="MAPPED")
    if commit:
        conn.commit()

    signaled = False
    if temporal_client is not None and not decided.noop:
        signal = ApprovalDecisionSignal(
            decision_id=f"slack:{decided.approval_id}:{intent.decision}:{uuid4().hex[:8]}",
            approval_id=str(decided.approval_id),
            action_id=str(decided.action_id),
            action_version=decided.action_version,
            status=intent.decision,
            decided_by=actor,
        )
        try:
            handle = temporal_client.get_workflow_handle(
                incident_workflow_id(row["incident_id"])
            )
            await handle.signal("approval_decision", signal)
            signaled = True
        except Exception:  # noqa: BLE001 — outbox dispatcher is fallback
            signaled = False

    verb = "Approved" if intent.decision == "APPROVED" else "Rejected"
    return SlackApprovalMapResult(
        ok=True,
        visible_message=(
            f"{verb} action {intent.action_id} v{intent.action_version} "
            f"(approval {intent.approval_id})."
        ),
        code=None,
        approval_id=intent.approval_id,
        action_id=intent.action_id,
        action_version=intent.action_version,
        decision=intent.decision,
        incident_id=row["incident_id"],
        workflow_signaled=signaled,
        interaction_status="MAPPED",
        noop=decided.noop,
    )
