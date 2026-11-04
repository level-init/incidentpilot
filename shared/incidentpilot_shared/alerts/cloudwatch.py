"""CloudWatch / SNS-style → normalized Alert (F3).

Accepts either:
- SNS ``Notification`` envelope with JSON ``Message`` (CW alarm state change)
- Direct CloudWatch alarm notification object

Produces the same ``NormalizedAlert`` shape as Alertmanager (F2).
"""

from __future__ import annotations

import json
from typing import Any

from incidentpilot_shared.alerts.types import (
    NormalizedAlert,
    fingerprint_for,
    parse_ts,
    str_map,
)


def _map_cw_state(raw: Any) -> str:
    state = str(raw or "ALARM").strip().upper()
    if state == "ALARM":
        return "firing"
    if state == "OK":
        return "resolved"
    if state == "INSUFFICIENT_DATA":
        return "suppressed"
    # Already domain-ish
    lowered = state.lower()
    if lowered in {"firing", "resolved", "suppressed"}:
        return lowered
    return "firing"


def _dimensions_to_labels(trigger: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    dims = trigger.get("Dimensions")
    if isinstance(dims, list):
        for item in dims:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("Name")
            value = item.get("value") or item.get("Value")
            if name is not None and value is not None:
                labels[str(name)] = str(value)
    return labels


def _unwrap_sns_or_direct(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the CloudWatch alarm body (unwrap SNS Message when present)."""
    msg = payload.get("Message")
    if isinstance(msg, str) and msg.strip().startswith("{"):
        try:
            parsed = json.loads(msg)
        except json.JSONDecodeError:
            return payload
        if isinstance(parsed, dict) and (
            "AlarmName" in parsed or "alarmName" in parsed or "NewStateValue" in parsed
        ):
            return parsed
    if isinstance(msg, dict) and ("AlarmName" in msg or "NewStateValue" in msg):
        return msg
    return payload


def cloudwatch_fingerprint(
    *,
    labels: dict[str, str],
    provider_fingerprint: str | None = None,
) -> str:
    return fingerprint_for(
        provider="cloudwatch",
        prefix="cw",
        labels=labels,
        provider_fingerprint=provider_fingerprint,
    )


def normalize_cloudwatch_alarm(raw: dict[str, Any]) -> NormalizedAlert:
    alarm = _unwrap_sns_or_direct(raw)
    alarm_name = str(alarm.get("AlarmName") or alarm.get("alarmName") or "").strip()
    region = str(alarm.get("Region") or alarm.get("region") or "").strip()
    account = str(alarm.get("AWSAccountId") or alarm.get("AccountId") or "").strip()
    trigger = alarm.get("Trigger") if isinstance(alarm.get("Trigger"), dict) else {}

    labels: dict[str, str] = {"alertname": alarm_name}
    if region:
        labels["region"] = region
    if account:
        labels["account_id"] = account
    labels.update(_dimensions_to_labels(trigger))

    new_state = alarm.get("NewStateValue") or alarm.get("newStateValue") or alarm.get("status")
    status = _map_cw_state(new_state)

    state_reason = alarm.get("NewStateReason") or alarm.get("AlarmDescription") or ""
    annotations = str_map(
        {
            "summary": state_reason,
            "description": alarm.get("AlarmDescription") or "",
            "old_state": alarm.get("OldStateValue") or "",
        }
    )

    state_time = parse_ts(alarm.get("StateChangeTime") or alarm.get("stateChangeTime"))
    starts_at = state_time if status == "firing" else None
    ends_at = state_time if status == "resolved" else None

    # Prefer ARN / AlarmName as vendor identity input when present.
    provider_fp = (
        str(alarm.get("AlarmArn") or alarm.get("AlarmName") or alarm_name).strip() or None
    )

    return NormalizedAlert(
        fingerprint=cloudwatch_fingerprint(
            labels=labels,
            provider_fingerprint=provider_fp,
        ),
        source="cloudwatch",
        status=status,
        labels=labels,
        annotations=annotations,
        starts_at=starts_at,
        ends_at=ends_at,
        raw_payload=dict(raw),
    )


def normalize_cloudwatch_payload(payload: dict[str, Any]) -> list[NormalizedAlert]:
    """Normalize one CW/SNS notification into ``NormalizedAlert`` list (0–1)."""
    if not isinstance(payload, dict):
        return []
    # SNS subscription confirmation has no alarm body — skip.
    if payload.get("Type") == "SubscriptionConfirmation":
        return []
    alarm = _unwrap_sns_or_direct(payload)
    if not (alarm.get("AlarmName") or alarm.get("alarmName") or alarm.get("NewStateValue")):
        return []
    return [normalize_cloudwatch_alarm(payload)]
