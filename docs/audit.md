# AuditEvent (L2)

Audit is the **security/compliance trail** — who authorized or changed what,
and when. It is distinct from Timeline (process chronicle) and from Evidence
(production observations).

| Concern | Store |
| --- | --- |
| What IncidentPilot did | `domain.timeline_event` ([timeline.md](timeline.md)) |
| Who approved / executed / admin-changed | `domain.audit_event` |
| What we observed in prod | `domain.evidence` ([evidence.md](evidence.md)) |

## Storage

Append-only `domain.audit_event` (`action`, `actor`, `resource_type`,
`resource_id`, `outcome`, `details`, optional `incident_id`). No updates; no
deletes (DB triggers).

Helper: `incidentpilot_shared.audit.append_audit_event` (caller owns TX).

`outcome` ∈ `success` | `denied` | `error`.

## Canonical actions

| `action` | When |
| --- | --- |
| `approval.decide` | Human/harness APPROVED or REJECTED (L2 AC) |
| `remediation.execute` | Durable RemediationResult → ACTION_RESULT insert (L2 AC) |
| `policy.evaluate` / `policy.publish` / `policy.activate` | Policy gate + admin policy versions |
| `admin.autonomy_upsert` | Autonomy config insert/update |
| `incident.create` / `incident.severity_update` | Incident create / severity rules |
| `incident.manual_resolve` | Contextual human resolve `RECOVERED→RESOLVED` with reason + health (M7) |
| `hypothesis.confirm` | SYSTEM confirmation gate |

## Web UI (M9)

Incident detail **Audit** panel lists these events (oldest first). Distinct
from Timeline. AI provenance lineage is a separate Admin-only panel
([web.md](web.md)).

## HTTP

```http
GET /incidents/{incident_id}/audit?order=asc
Authorization: Bearer local-dev
```

- Default `order=desc`; `order=asc` for oldest-first
- Cap 200; requires `incident:read`
- Global (non-incident) admin audits such as `policy.publish` are not listed
  here — they keep `incident_id` NULL

## Retention

Retain `audit_event` **at least as long as related objects** it references
(approvals, policy decisions, execution attempts, autonomy/policy config, and
the incident itself). Do not purge audit rows while the incident, its
approvals, or remediation attempts remain queryable. Prefer archive over
delete; the table is append-only by design.
