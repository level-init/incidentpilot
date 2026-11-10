# Slack notifier (K1–K4)

Outbound incident briefs/updates are **BEST_EFFORT**: domain commits first
(with a transactional outbox row); Slack delivery failures **never** roll back
Incident state (`MITIGATING` / `VALIDATING` stay intact).

## Inbound verify (K2)

`POST /webhooks/slack/interactions` — **api-only** HMAC with
`SLACK_SIGNING_SECRET` (`X-Slack-Signature` / `X-Slack-Request-Timestamp`).

1. Reject invalid / stale signatures (**401**) — no DB write  
2. Persist `domain.slack_interaction` (`status=RECEIVED`)  
3. Then return **200** (`accepted` / `duplicate`)

Idempotency scope: `webhook:slack_interaction` (Slack `trigger_id` or body hash).

## Approve / reject → ApprovalDecision (K3)

Block Kit button `value` JSON (see `encode_slack_approval_value`):

```json
{
  "approval_id": "<uuid>",
  "action_id": "<uuid>",
  "action_version": 1,
  "decision": "APPROVED"
}
```

`action_id` on the button may be `ip_approve` / `ip_reject`.

After persist, the api maps the interaction:

1. Version / action mismatch → ephemeral text includes `STALE_ACTION_VERSION`
   (HTTP **200**, interaction `FAILED`, approval stays `PENDING`)
2. Match + `REQUIRE_APPROVAL` → `decide_approval_command` (`decided_by=slack:<user>`),
   mark interaction `MAPPED`, signal `approval_decision` (Level 2 wait resumes)

```bash
# fixture: sign body with SLACK_SIGNING_SECRET (see tests/test_slack_verify_k2.py)
curl -s -X POST http://localhost:8000/webhooks/slack/interactions \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Slack-Request-Timestamp: $TS" \
  -H "X-Slack-Signature: $SIG" \
  --data-urlencode 'payload={"type":"block_actions","trigger_id":"…"}'
```

## Lifecycle thread updates (K4)

Coherent Slack thread across the incident:

| Template | Role |
| --- | --- |
| `brief` | Root message (opens thread) |
| `evidence` | Thread reply — evidence highlight |
| `status` / `update` | Thread reply — state change |
| `recovery` | Thread reply — validation / recovery |
| `postmortem` | Thread reply — postmortem link |

- Root `ts` stored in `domain.slack_incident_thread`
- Replies resolve `thread_ts` at deliver time if omitted
- UI deep link: `INCIDENTPILOT_WEB_BASE_URL` + `/incidents/{public_id}`
  (default `http://localhost:3000`)

```python
from incidentpilot_shared import enqueue_slack_lifecycle_thread, enqueue_slack_notify

enqueue_slack_lifecycle_thread(
    conn,
    incident_id=…,
    channel="#incidents",
    public_id="INC-…",
    title="checkout 5xx",
    commit=True,
)
# then: python -m incidentpilot_worker notify once
```

### Demo checklist

1. `make migrate` (includes `0017_k4_slack_incident_thread`)
2. Seed / pick an incident `public_id`
3. `enqueue_slack_lifecycle_thread(...)` + `notify once`
4. Confirm Slack (or `FakeSlackNotifier.posts`): one root + four replies with
   same `thread_ts`, each kind present, UI link in every message

## Slash commands (K6)

`POST /webhooks/slack/commands` — same HMAC as interactions. Point Slack
`/ip` at this URL. ChatOps is **BEST_EFFORT** and never blocks remediation.

| Command | Authz | Behavior |
| --- | --- | --- |
| `status` `evidence` `hypotheses` `timeline` `impact` | any verified Slack user | Read incident summary |
| `approve` `reject` | responder allowlist | Decide PENDING approval |
| `escalate` | responder allowlist | HUMAN_OBSERVATION note; DEGRADED when legal |
| `resolve` | responder allowlist | `RECOVERED` → `RESOLVED` when legal |
| `help` | any | Command list |

```text
/ip status INC-ABC123
/ip evidence INC-ABC123
/ip resolve INC-ABC123
```

Authz env:

| Var | Meaning |
| --- | --- |
| `SLACK_COMMAND_RESPONDERS` | Comma-separated Slack user ids allowed to mutate |
| `SLACK_COMMANDS_OPEN=1` | Local/demo: all users may mutate |

### Manual verify list

1. Configure Slack slash `/ip` → `https://<api>/webhooks/slack/commands`
2. Set `SLACK_SIGNING_SECRET` on api; `SLACK_COMMANDS_OPEN=1` for demos
3. `/ip status <public_id>` → state + UI link
4. `/ip evidence <public_id>` → latest evidence rows
5. `/ip resolve <public_id>` on a `RECOVERED` incident → `RESOLVED`
6. Mutate as non-allowlisted user (without open mode) → Forbidden

## Privilege split

| Process | Cred | Role |
| --- | --- | --- |
| `incidentpilot-api` | `SLACK_SIGNING_SECRET` | verify inbound interactions (K2) |
| `python -m incidentpilot_worker notify` | `SLACK_BOT_TOKEN` (when `SLACK_NOTIFIER=http`) | outbox → `chat.postMessage` |
| `incidentpilot-worker` (general / AI) | **no** Slack token / signing secret | LLM + orchestration only |

`AI_FORBIDDEN_SLACK_ENV` = `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`.

## Outbox event

| `event_type` | Payload (high level) | Delivered by |
| --- | --- | --- |
| `slack.notify` | `channel`, `template`, rendered `text`/`blocks`, optional `thread_ts`, `ui_url`, `side_effect=BEST_EFFORT` | notify process |

Temporal outbox dispatch (`dispatch`) **skips** `slack.notify` (releases lease)
so Slack stays off the signal path.

```bash
python -m incidentpilot_worker notify once
python -m incidentpilot_worker notify
```

## Fault inject

```python
from incidentpilot_adapters.slack import FakeSlackNotifier, set_fake_slack_notifier

fake = FakeSlackNotifier(fail=True)
set_fake_slack_notifier(fake)
# notify_once → outbox stays pending; incident.state unchanged
```

## Env

| Var | Default | Notes |
| --- | --- | --- |
| `SLACK_SIGNING_SECRET` | — | **api only** — inbound HMAC (K2) |
| `SLACK_NOTIFIER` | `fake` | `fake` / `http` |
| `SLACK_BOT_TOKEN` | — | required for `http`; notify process only |
| `INCIDENTPILOT_WEB_BASE_URL` | `http://localhost:3000` | UI deep links in templates (K4) |
