"""M5: Remediation panel aggregate — action scope, policy, approval, attempts."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from psycopg.rows import dict_row

from incidentpilot_api.auth import Principal, get_principal
from incidentpilot_api.db import get_conn
from incidentpilot_api.rbac import Permission, require_permission
from incidentpilot_api.schemas import (
    RemediationActionOut,
    RemediationApprovalOut,
    RemediationAttemptOut,
    RemediationPolicyOut,
)

router = APIRouter(tags=["remediation"])

_UNSAFE_RECONCILE = frozenset({"UNKNOWN", "PARTIAL"})


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _attempt_out(row: dict[str, object]) -> RemediationAttemptOut:
    adapter = _as_dict(row.get("adapter_result"))
    recon = adapter.get("reconciliation_state")
    recon_s = None if recon is None else str(recon)
    state = str(row["state"])
    unsafe = state == "UNKNOWN" or recon_s in _UNSAFE_RECONCILE
    return RemediationAttemptOut(
        id=row["id"],  # type: ignore[arg-type]
        action_version=int(row["action_version"]),  # type: ignore[arg-type]
        attempt_number=int(row["attempt_number"]),  # type: ignore[arg-type]
        state=state,
        error_summary=None if row["error_summary"] is None else str(row["error_summary"]),
        reconciliation_state=recon_s,
        adapter_result=adapter,
        unsafe_to_retry=unsafe,
    )


@router.get(
    "/incidents/{incident_id}/remediation",
    response_model=list[RemediationActionOut],
    summary="Remediation panel cards (scope / policy / approval / attempts)",
)
def list_remediation(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(get_principal)],
    conn: Annotated[Connection, Depends(get_conn)],
) -> list[RemediationActionOut]:
    require_permission(principal, Permission.INCIDENT_READ)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT 1 FROM domain.incident WHERE id = %s", (str(incident_id),))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="incident not found")

        cur.execute(
            """
            SELECT a.id AS action_id, a.action_type, a.status, a.current_version,
                   a.is_reversible, av.parameters, av.target_ref,
                   pd.decision AS policy_decision, pd.reason AS policy_reason,
                   pd.policy_key, pd.policy_version,
                   ap.id AS approval_id, ap.status AS approval_status,
                   ap.decided_by, ap.action_version AS approval_version
            FROM domain.action a
            JOIN domain.action_version av
              ON av.action_id = a.id AND av.version = a.current_version
            LEFT JOIN domain.policy_decision pd
              ON pd.action_id = a.id AND pd.action_version = a.current_version
            LEFT JOIN domain.approval ap
              ON ap.action_id = a.id AND ap.action_version = a.current_version
            WHERE a.incident_id = %s
            ORDER BY a.created_at DESC
            LIMIT 50
            """,
            (str(incident_id),),
        )
        actions = list(cur.fetchall())
        if not actions:
            return []

        action_ids = [str(row["action_id"]) for row in actions]
        cur.execute(
            """
            SELECT id, action_id, action_version, attempt_number, state,
                   error_summary, adapter_result
            FROM domain.execution_attempt
            WHERE action_id = ANY(%s::uuid[])
            ORDER BY action_id, attempt_number DESC
            """,
            (action_ids,),
        )
        attempts_by_action: dict[str, list[RemediationAttemptOut]] = {}
        for row in cur.fetchall():
            aid = str(row["action_id"])
            attempts_by_action.setdefault(aid, []).append(_attempt_out(row))

    cards: list[RemediationActionOut] = []
    for row in actions:
        policy = None
        if row["policy_decision"] is not None:
            policy = RemediationPolicyOut(
                decision=str(row["policy_decision"]),
                reason=None if row["policy_reason"] is None else str(row["policy_reason"]),
                policy_key=None if row["policy_key"] is None else str(row["policy_key"]),
                policy_version=(
                    None if row["policy_version"] is None else str(row["policy_version"])
                ),
            )
        approval = None
        if row["approval_id"] is not None:
            approval = RemediationApprovalOut(
                id=row["approval_id"],  # type: ignore[arg-type]
                action_version=int(row["approval_version"]),  # type: ignore[arg-type]
                status=str(row["approval_status"]),
                decided_by=(None if row["decided_by"] is None else str(row["decided_by"])),
            )
        reversible = bool(row["is_reversible"])
        cards.append(
            RemediationActionOut(
                action_id=row["action_id"],  # type: ignore[arg-type]
                action_type=str(row["action_type"]),
                status=str(row["status"]),
                current_version=int(row["current_version"]),  # type: ignore[arg-type]
                is_reversible=reversible,
                risk="reversible" if reversible else "irreversible",
                parameters=_as_dict(row.get("parameters")),
                target_ref=_as_dict(row.get("target_ref")),
                policy=policy,
                approval=approval,
                attempts=attempts_by_action.get(str(row["action_id"]), []),
            )
        )
    return cards
