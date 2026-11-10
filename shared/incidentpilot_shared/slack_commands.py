"""Slack slash-command handlers (K6) — ChatOps; never blocks core remediation.

Commands are BEST_EFFORT UX over an active incident. Authz: read commands for
any verified Slack caller; mutate commands require responder-class Slack users
(``SLACK_COMMAND_RESPONDERS`` allowlist, or open mode for local demos).
"""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from incidentpilot_shared.domain.commands import (
    decide_approval_command,
    transition_incident_command,
)
from incidentpilot_shared.domain.transitions import (
    IllegalTransitionError,
    IncidentState,
    StaleRevisionError,
)
from incidentpilot_shared.slack_approval import slack_actor_id
from incidentpilot_shared.slack_notify import incident_ui_url

if TYPE_CHECKING:
    from psycopg import Connection

READ_COMMANDS = frozenset(
    {"status", "evidence", "hypotheses", "timeline", "impact", "help"}
)
MUTATE_COMMANDS = frozenset({"approve", "reject", "escalate", "resolve"})
ALL_COMMANDS = READ_COMMANDS | MUTATE_COMMANDS


@dataclass(frozen=True, slots=True)
class SlashCommandResult:
    text: str
    response_type: str = "ephemeral"
    ok: bool = True
    code: str | None = None


def slack_user_may_mutate(slack_user_id: str) -> bool:
    """Responder-class gate for approve/reject/escalate/resolve."""
    if (os.environ.get("SLACK_COMMANDS_OPEN") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "open",
    }:
        return True
    raw = (os.environ.get("SLACK_COMMAND_RESPONDERS") or "").strip()
    if not raw:
        return False
    allowed = {p.strip() for p in raw.split(",") if p.strip()}
    return slack_user_id in allowed


def _resolve_incident(
    conn: Connection, token: str
) -> tuple[UUID, str, str, int] | None:
    """Return (id, public_id, state, revision) by public_id or UUID."""
    token = token.strip()
    with conn.cursor() as cur:
        if len(token) == 36 and token.count("-") == 4:
            cur.execute(
                """
                SELECT id, public_id, state, incident_revision
                FROM domain.incident WHERE id = %s
                """,
                (token,),
            )
        else:
            cur.execute(
                """
                SELECT id, public_id, state, incident_revision
                FROM domain.incident WHERE lower(public_id) = lower(%s)
                """,
                (token,),
            )
        row = cur.fetchone()
    if row is None:
        return None
    return UUID(str(row[0])), str(row[1]), str(row[2]), int(row[3])


def parse_slash_text(text: str) -> tuple[str, list[str]]:
    """Parse ``status INC-ABC`` → ``(\"status\", [\"INC-ABC\"])``."""
    raw = (text or "").strip()
    if not raw:
        return "help", []
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()
    if not parts:
        return "help", []
    return parts[0].lower(), parts[1:]


def _help_text() -> str:
    return (
        "*IncidentPilot slash commands* (`/ip <cmd> <incident>`)\n"
        "• `status` `evidence` `hypotheses` `timeline` `impact` — read\n"
        "• `approve` `reject` — pending approval for incident\n"
        "• `escalate` — record human escalate note (does not block remediation)\n"
        "• `resolve` — RECOVERED→RESOLVED when legal\n"
        "ChatOps is BEST_EFFORT — core remediation path is never blocked."
    )


def _fmt_status(public_id: str, state: str, title: str, revision: int) -> str:
    link = incident_ui_url(public_id)
    return (
        f"*{public_id}* — `{state}` (rev {revision})\n"
        f"{title}\n<{link}|Open in IncidentPilot>"
    )


def handle_slash_command(
    conn: Connection,
    *,
    text: str,
    slack_user_id: str,
    commit: bool = True,
) -> SlashCommandResult:
    """Dispatch a verified slash-command body against domain state."""
    cmd, args = parse_slash_text(text)
    if cmd == "help" or cmd not in ALL_COMMANDS:
        return SlashCommandResult(
            text=_help_text(),
            ok=cmd == "help",
            code=None if cmd == "help" else "UNKNOWN_COMMAND",
        )

    if cmd in MUTATE_COMMANDS and not slack_user_may_mutate(slack_user_id):
        return SlashCommandResult(
            text=(
                "Forbidden: your Slack user is not in `SLACK_COMMAND_RESPONDERS` "
                "(or set `SLACK_COMMANDS_OPEN=1` for local demos)."
            ),
            ok=False,
            code="FORBIDDEN",
        )

    if not args:
        return SlashCommandResult(
            text=f"Usage: `/ip {cmd} <public_id|incident_uuid>`",
            ok=False,
            code="USAGE",
        )

    incident = _resolve_incident(conn, args[0])
    if incident is None:
        return SlashCommandResult(
            text=f"Incident not found: `{args[0]}`",
            ok=False,
            code="NOT_FOUND",
        )
    incident_id, public_id, state, revision = incident

    if cmd == "status":
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title FROM domain.incident WHERE id = %s",
                (str(incident_id),),
            )
            title = str(cur.fetchone()[0])
        return SlashCommandResult(text=_fmt_status(public_id, state, title, revision))

    if cmd == "evidence":
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT evidence_key, kind, summary
                FROM domain.evidence
                WHERE incident_id = %s
                ORDER BY observed_at DESC LIMIT 8
                """,
                (str(incident_id),),
            )
            rows = cur.fetchall()
        if not rows:
            return SlashCommandResult(text=f"*{public_id}*: no evidence yet.")
        lines = [f"*{public_id}* evidence (latest {len(rows)}):"]
        for key, kind, summary in rows:
            lines.append(f"• `{key}` [{kind}] {summary}")
        return SlashCommandResult(text="\n".join(lines))

    if cmd == "hypotheses":
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, statement, confidence, rank
                FROM domain.hypothesis
                WHERE incident_id = %s
                ORDER BY rank NULLS LAST, created_at DESC LIMIT 8
                """,
                (str(incident_id),),
            )
            rows = cur.fetchall()
        if not rows:
            return SlashCommandResult(text=f"*{public_id}*: no hypotheses yet.")
        lines = [f"*{public_id}* hypotheses:"]
        for status, statement, confidence, rank in rows:
            lines.append(
                f"• [{status}] r={rank} conf={confidence}: {statement}"
            )
        return SlashCommandResult(text="\n".join(lines))

    if cmd == "timeline":
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_type, summary, actor
                FROM domain.timeline_event
                WHERE incident_id = %s
                ORDER BY created_at DESC LIMIT 10
                """,
                (str(incident_id),),
            )
            rows = cur.fetchall()
        if not rows:
            return SlashCommandResult(text=f"*{public_id}*: timeline empty.")
        lines = [f"*{public_id}* timeline:"]
        for event_type, summary, actor in rows:
            lines.append(f"• `{event_type}` ({actor}): {summary}")
        return SlashCommandResult(text="\n".join(lines))

    if cmd == "impact":
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT severity, customer_impact_summary, captured_at
                FROM domain.impact_snapshot
                WHERE incident_id = %s
                ORDER BY captured_at DESC LIMIT 3
                """,
                (str(incident_id),),
            )
            rows = cur.fetchall()
        if not rows:
            return SlashCommandResult(text=f"*{public_id}*: no impact snapshots.")
        lines = [f"*{public_id}* impact:"]
        for severity, summary, captured_at in rows:
            lines.append(f"• `{severity}` @ {captured_at}: {summary}")
        return SlashCommandResult(text="\n".join(lines))

    if cmd in {"approve", "reject"}:
        return _decide_pending(
            conn,
            incident_id=incident_id,
            public_id=public_id,
            decision="APPROVED" if cmd == "approve" else "REJECTED",
            slack_user_id=slack_user_id,
            commit=commit,
        )

    if cmd == "escalate":
        return _escalate(
            conn,
            incident_id=incident_id,
            public_id=public_id,
            state=state,
            revision=revision,
            slack_user_id=slack_user_id,
            commit=commit,
        )

    if cmd == "resolve":
        return _resolve(
            conn,
            incident_id=incident_id,
            public_id=public_id,
            state=state,
            revision=revision,
            slack_user_id=slack_user_id,
            commit=commit,
        )

    return SlashCommandResult(text=_help_text(), ok=False, code="UNKNOWN_COMMAND")


def _decide_pending(
    conn: Connection,
    *,
    incident_id: UUID,
    public_id: str,
    decision: str,
    slack_user_id: str,
    commit: bool,
) -> SlashCommandResult:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.action_id, a.action_version, pd.decision
            FROM domain.approval a
            JOIN domain.action act ON act.id = a.action_id
            LEFT JOIN domain.policy_decision pd
              ON pd.action_id = a.action_id
             AND pd.action_version = a.action_version
            WHERE act.incident_id = %s AND a.status = 'PENDING'
            ORDER BY a.created_at DESC
            LIMIT 1
            """,
            (str(incident_id),),
        )
        row = cur.fetchone()
    if row is None:
        return SlashCommandResult(
            text=f"*{public_id}*: no PENDING approval.",
            ok=False,
            code="NO_PENDING_APPROVAL",
        )
    approval_id, action_id, action_version, policy = row
    if str(policy) == "BLOCK":
        return SlashCommandResult(
            text=f"*{public_id}*: PolicyDecision is BLOCK — cannot {decision.lower()}.",
            ok=False,
            code="POLICY_BLOCK",
        )
    try:
        decide_approval_command(
            conn,
            action_id=UUID(str(action_id)),
            action_version=int(action_version),
            status=decision,
            decided_by=slack_actor_id(slack_user_id),
            commit=commit,
        )
    except Exception as exc:  # noqa: BLE001 — surface to Slack UX
        return SlashCommandResult(
            text=f"*{public_id}*: decide failed: {exc}",
            ok=False,
            code="DECIDE_FAILED",
        )
    return SlashCommandResult(
        text=(
            f"*{public_id}*: {decision} approval `{approval_id}` "
            f"(action {action_id} v{action_version}). "
            "Workflow will resume via outbox signal (non-blocking)."
        )
    )


def _escalate(
    conn: Connection,
    *,
    incident_id: UUID,
    public_id: str,
    state: str,
    revision: int,
    slack_user_id: str,
    commit: bool,
) -> SlashCommandResult:
    """Record escalate as HUMAN_OBSERVATION; optionally move to DEGRADED when legal."""
    from incidentpilot_shared.domain.commands import append_evidence_command

    actor = slack_actor_id(slack_user_id)
    append_evidence_command(
        conn,
        incident_id=incident_id,
        kind="HUMAN_OBSERVATION",
        fingerprint=f"slack-escalate:{actor}:{uuid4().hex}",
        summary=f"Escalated via Slack slash command by {actor}",
        producer=f"session:{actor}",
        payload={"via": "slash", "command": "escalate"},
        provenance={
            "actor_id": actor,
            "source": "HUMAN_OBSERVATION",
            "truthfulness": "human_note",
            "absolute_truth": False,
            "slash_command": "escalate",
        },
        commit=False,
    )
    note = f"*{public_id}*: escalate noted (state remains `{state}`)."
    if state in {
        IncidentState.DIAGNOSED.value,
        IncidentState.AWAITING_APPROVAL.value,
        IncidentState.MITIGATING.value,
        IncidentState.VALIDATING.value,
        IncidentState.RECOVERED.value,
    }:
        try:
            transition_incident_command(
                conn,
                incident_id=incident_id,
                expected_revision=revision,
                to_state=IncidentState.DEGRADED,
                actor=actor,
                commit=False,
            )
            note = f"*{public_id}*: escalated → `DEGRADED` (ChatOps; remediation path not blocked)."
        except (IllegalTransitionError, StaleRevisionError, Exception):
            # Keep observation; do not fail the slash UX hard.
            note = (
                f"*{public_id}*: escalate noted; could not transition to DEGRADED "
                f"from `{state}` (left unchanged)."
            )
    if commit:
        conn.commit()
    return SlashCommandResult(text=note)


def _resolve(
    conn: Connection,
    *,
    incident_id: UUID,
    public_id: str,
    state: str,
    revision: int,
    slack_user_id: str,
    commit: bool,
) -> SlashCommandResult:
    actor = slack_actor_id(slack_user_id)
    if state != IncidentState.RECOVERED.value:
        return SlashCommandResult(
            text=(
                f"*{public_id}*: resolve requires `RECOVERED` (current `{state}`). "
                "Core path unchanged."
            ),
            ok=False,
            code="ILLEGAL_RESOLVE",
        )
    try:
        transition_incident_command(
            conn,
            incident_id=incident_id,
            expected_revision=revision,
            to_state=IncidentState.RESOLVED,
            actor=actor,
            commit=commit,
        )
    except (IllegalTransitionError, StaleRevisionError) as exc:
        return SlashCommandResult(
            text=f"*{public_id}*: resolve failed: {exc}",
            ok=False,
            code="RESOLVE_FAILED",
        )
    return SlashCommandResult(text=f"*{public_id}*: resolved (`RECOVERED` → `RESOLVED`).")


def slash_form_to_dict(form: dict[str, Any]) -> dict[str, str]:
    """Normalize Slack slash form fields (values may be lists from parse_qs)."""
    out: dict[str, str] = {}
    for key, value in form.items():
        if isinstance(value, list):
            out[key] = str(value[0]) if value else ""
        else:
            out[key] = str(value)
    return out


def dump_command_catalog() -> str:
    """Stable docs/test helper listing supported commands."""
    return json.dumps(
        {
            "read": sorted(READ_COMMANDS),
            "mutate": sorted(MUTATE_COMMANDS),
        },
        sort_keys=True,
    )
