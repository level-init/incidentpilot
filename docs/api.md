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
curl -s -H 'Authorization: Bearer local-dev' http://localhost:8000/auth/me
curl -s -H 'Authorization: Bearer local-dev' http://localhost:8000/incidents
curl -s -H 'Authorization: Bearer local-dev' \
  'http://localhost:8000/incidents?state=DETECTED&service=checkout'
curl -s -X POST -H 'Authorization: Bearer local-dev' \
  -H 'Content-Type: application/json' \
  -d '{"title":"demo","severity":"SEV2","service_key":"checkout"}' \
  http://localhost:8000/incidents
```

`GET /incidents` returns `service_keys[]` / `environments[]` and accepts
`state` / `severity` / `service` query filters (M2). `GET /incidents/{id}`
accepts UUID or `public_id` (M3 header + Slack deep links).

`GET /evidence?incident_id=` and `GET /hypotheses?incident_id=` include
`provenance` (and hypotheses also `cited_evidence_ids`) for the M4 panes.

`GET /incidents/{id}/remediation` returns remediation cards (params, risk,
policy, approval, attempts with `unsafe_to_retry` for UNKNOWN/PARTIAL) for M5.

M6 context:

- `GET /incidents/{id}/changes` — changes for linked services
- `GET /incidents/{id}/runbook` — pinned runbook with `allowed_action_types`
  (authority) and `body_markdown` (untrusted prose)

M8 admin (Admin / `admin:config` only):

- `GET /admin/policies` — policy keys + active/latest versions
- `GET/POST /admin/runbooks`, `POST …/versions`, `POST …/publish` — catalog + publish
- `GET /admin/integrations` — connector scope/health; **never returns secrets**

Policy version history/publish/activate remain under `/policies/{key}/versions`
(I7). Dashboard admin UI: [web.md](web.md).

M7 contextual manual resolve (no generic Resolve):

- `GET /incidents/{id}/resolve-context` — `eligible` only when state is
  `RECOVERED`; includes validation health
- `POST /incidents/{id}/resolve` — reason + revision; audits
  `incident.manual_resolve`; `RECOVERED → RESOLVED`

Dashboard: [web.md](web.md) (`make web-dev`).

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

## Postmortem draft + FINAL (L4–L5)

```http
POST /incidents/{incident_id}/postmortem/draft
Authorization: Bearer local-dev
Content-Type: application/json

{}
```

```http
POST /incidents/{incident_id}/postmortem/finalize
Authorization: Bearer local-dev
Content-Type: application/json

{"corrective_actions":[{"title":"Add deploy canary","owner":"platform"}]}
```

- Draft after **RESOLVED**; finalize sets **FINAL** + `corrective_actions[]`
- `POSTMORTEM → CLOSED` refused without FINAL (**409**)
- `GET /incidents/{id}/postmortem/export` — L6 package (timeline + evidence refs + body)
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
