# TimelineEvent (L1)

Timeline answers **what IncidentPilot did** — the process chronicle for humans
and postmortems. It is **not** Evidence and must not be treated as production
facts. Evidence answers what we observed about the production system; a
timeline row may *reference* evidence, actions, or approvals, but never
substitutes for them.

## Storage

Append-only `domain.timeline_event` (`incident_id`, `event_type`, `summary`,
`actor`, `occurred_at`, `payload`). No updates; no deletes.

Helper: `incidentpilot_shared.timeline.append_timeline_event` (caller owns TX).

## Canonical event types

| `event_type` | Typical emitter |
| --- | --- |
| `INCIDENT_CREATED` | `create_incident_command` |
| `STATE_TRANSITION` | `transition_incident_command` |
| `HYPOTHESIS_LEADING` / `HYPOTHESIS_CONFIRMED` | diagnose / confirm |
| `RUNBOOK_PINNED` | `pin_runbook_version_command` |
| `SEVERITY_UPDATE` | `update_incident_severity_command` |
| `ACTION_PROPOSED` / `COMPENSATION_PROPOSED` | propose action paths |
| `POLICY_DECISION` | `evaluate_policy_command` |
| `APPROVAL_CREATED` / `APPROVAL_DECIDED` / `APPROVAL_TIMEOUT` | approval commands |
| `EXECUTION_ATTEMPT_RESERVED` | `reserve_execution_attempt_command` |
| `REMEDIATION_RESULT` | `append_action_result_evidence_command` (on insert) |
| `VALIDATION_RECORDED` | `record_validation_result_command` (on insert) |
| `VALIDATION_ROUTED` | `route_validation_outcome_command` |

## HTTP

```http
GET /incidents/{incident_id}/timeline?order=asc
Authorization: Bearer local-dev
```

- Default `order=desc` (newest first; dashboard-friendly)
- `order=asc` — oldest first (readable bad-deploy chronology)
- Cap: 200 rows
- Requires `incident:read`

## Bad-deploy chronology (acceptance)

Along a Level-2 rollback path, the event-type sequence includes at least:

`INCIDENT_CREATED` → `STATE_TRANSITION` → `ACTION_PROPOSED` → `POLICY_DECISION`
→ `APPROVAL_CREATED` → `APPROVAL_DECIDED` → `EXECUTION_ATTEMPT_RESERVED`
→ `REMEDIATION_RESULT` → `VALIDATION_RECORDED` → `VALIDATION_ROUTED`

(Extra transitions and milestones may appear between these.)
