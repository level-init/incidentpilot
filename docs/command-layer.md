# Shared domain command layer (B7)

API and workers share one mutation surface so revision checks, legal
transitions, and outbox rules cannot be bypassed.

## Import path

| Deployable | Module |
| --- | --- |
| Shared implementation | `incidentpilot_shared.domain.commands` |
| API | `incidentpilot_api.commands` (re-export) |
| Worker | `incidentpilot_worker.commands` (re-export) |

## Commands

| Command | Purpose |
| --- | --- |
| `transition_incident_command` | State machine + revision + timeline + outbox |
| `append_evidence_command` | Append-only Evidence insert |
| `decide_approval_command` | PENDING → APPROVED/REJECTED |
| `reserve_execution_attempt_command` | Reserve attempt before MITIGATING |
| `upsert_alert_command` | Insert/update `domain.alert` by fingerprint (F2) |

## Adapter boundary

`incidentpilot_adapters` must not write `domain.*` tables. Adapters are for
outbound I/O; commands own domain mutations.
