# HTTP API

## Auth (C1 session identity)

```http
Authorization: Bearer local-dev
```

See [auth.md](auth.md). Do **not** send `actor_id` / `actor` / `decided_by` in bodies.

Stub tokens: `local-dev` (responder), `local-dev-admin`, `local-dev-viewer`.

- Missing/invalid bearer → **401**
- Role not permitted → **403**
- Spoofed identity fields in JSON body → **400**

## Local run

```bash
make bootstrap
make compose-core && make migrate
make api-run
```

```bash
curl -s http://localhost:8000/health
curl -s -H 'Authorization: Bearer local-dev' http://localhost:8000/incidents
curl -s -X POST -H 'Authorization: Bearer local-dev' \
  -H 'Content-Type: application/json' \
  -d '{"title":"demo"}' \
  http://localhost:8000/incidents
```

Published contract: [openapi/openapi.json](../openapi/openapi.json) (`make openapi-export`).

## Approval harness (I6)

Eval/test path for Level-2 approvals without Slack (real `domain.approval` rows):

```bash
# requires eval entitlement (local-dev-evaluator)
curl -s -X POST -H 'Authorization: Bearer local-dev-evaluator' \
  -H 'Content-Type: application/json' \
  -d '{"status":"APPROVED"}' \
  http://localhost:8000/eval/approvals/<approval_id>/decide

python scripts/approval_harness.py reject <approval_id>
```

Ops `/approvals/{id}/decide` remains the human/session path. Harness requires
`eval_entitled`; approve resumes `wait_for_approval`, reject replans to `DIAGNOSED`.

## Policy versioning (I7)

```bash
# Admin publishes a new immutable version (optionally activates)
curl -s -X POST -H 'Authorization: Bearer local-dev-admin' \
  -H 'Content-Type: application/json' \
  -d '{"body":{"block_action_types":["OTHER"]},"notes":"tighten","activate":true}' \
  http://localhost:8000/policies/default/versions

curl -s -H 'Authorization: Bearer local-dev' \
  http://localhost:8000/policies/default/versions
```

Past `PolicyDecision` rows keep their stamped `policy_version`; definitions are append-only.

## HUMAN_OBSERVATION (K5)

```bash
curl -s -X POST -H 'Authorization: Bearer local-dev' \
  -H 'Content-Type: application/json' \
  -d '{"summary":"saw elevated errors in checkout"}' \
  http://localhost:8000/incidents/<id>/observations
```

- Requires Responder+ (`observation:write`); Viewer → **403**
- `kind=HUMAN_OBSERVATION`, `producer=session:<actor_id>`
- `provenance.actor_id` from session only; client `actor_id` → **400**
- Notes are `truthfulness=human_note` (not absolute truth)

## Timeline (L1)

```http
GET /incidents/{incident_id}/timeline?order=asc
Authorization: Bearer local-dev
```

- Process chronicle (`TimelineEvent`) — **not** Evidence
- `order=desc` (default) or `order=asc` for oldest-first readable chronology
- Cap 200; requires `incident:read`
- See [timeline.md](timeline.md)

## Postmortem draft (L4)

```http
POST /incidents/{incident_id}/postmortem/draft
Authorization: Bearer local-dev
Content-Type: application/json

{}
```

- Requires incident **RESOLVED**; uncited/unsupported claims → **400**
- Auto-generates grounded claims from Evidence/Timeline/Action/ValidationResult
- See [postmortem.md](postmortem.md)

## AIInvocation provenance (L3)

```http
GET /ai-invocations/{invocation_id}/provenance
Authorization: Bearer local-dev-admin
```

- Admin-gated (`admin:config`); answers which Evidence IDs were supplied
- Includes `input_evidence_ids`, `artifact_uri`, request/response metadata
- See [llm.md](llm.md)

## Audit (L2)

```http
GET /incidents/{incident_id}/audit?order=asc
Authorization: Bearer local-dev
```

- Privileged who/what/when (`AuditEvent`) — **not** Timeline
- Approve + execute (and policy/admin) writers; retention ≥ related objects
- Cap 200; requires `incident:read`
- See [audit.md](audit.md)

## Slack slash commands (K6)

`POST /webhooks/slack/commands` — HMAC-verified `/ip` ChatOps
(status/evidence/hypotheses/timeline/impact/approve/reject/escalate/resolve).
See [slack.md](slack.md). Does **not** block the remediation path.

## Slack interactions (K2)

`POST /webhooks/slack/interactions` — Slack signing-secret HMAC on **api** only.
Persist `domain.slack_interaction` before **200**, then map approve/reject to
`ApprovalDecision` (K3; stale versions visible in ephemeral `text`).
See [slack.md](slack.md).

## Alertmanager webhook (F1–F5)

Separate ingress (not Slack HMAC): `POST /webhooks/alerts/alertmanager`.

Normalizes to `domain.alert`, correlates by fingerprint / time / `labels.service`,
then idempotently starts `IncidentWorkflow` (→ INVESTIGATING).
See [alert-webhooks.md](alert-webhooks.md) for auth, replay, correlation, and verify curls.
