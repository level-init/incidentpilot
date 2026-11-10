# Slack notifier (K1)

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
ApprovalDecision mapping is **K3**.

```bash
# fixture: sign body with SLACK_SIGNING_SECRET (see tests/test_slack_verify_k2.py)
curl -s -X POST http://localhost:8000/webhooks/slack/interactions \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Slack-Request-Timestamp: $TS" \
  -H "X-Slack-Signature: $SIG" \
  --data-urlencode 'payload={"type":"block_actions","trigger_id":"…"}'
```

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
| `slack.notify` | `channel`, `template` (`brief`\|`update`), rendered `text`/`blocks`, `side_effect=BEST_EFFORT` | notify process |

Temporal outbox dispatch (`dispatch`) **skips** `slack.notify` (releases lease)
so Slack stays off the signal path.

```python
from incidentpilot_shared import enqueue_slack_notify

enqueue_slack_notify(
    conn,
    incident_id=…,
    channel="#incidents",
    template="brief",  # or "update"
    public_id="INC-…",
    title="…",
    state="MITIGATING",
    summary="Rolling back checkout",
)
conn.commit()
```

```bash
python -m incidentpilot_worker notify once
python -m incidentpilot_worker notify
```

## Templates

| Template | Use |
| --- | --- |
| `brief` | High-signal incident brief (header + state + summary) |
| `update` | Status / recovery note |

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
