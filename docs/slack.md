# Slack notifier (K1)

Outbound incident briefs/updates are **BEST_EFFORT**: domain commits first
(with a transactional outbox row); Slack delivery failures **never** roll back
Incident state (`MITIGATING` / `VALIDATING` stay intact).

Inbound verify / approvals are **K2+** (out of scope here).

## Privilege split

| Process | Cred | Role |
| --- | --- | --- |
| `python -m incidentpilot_worker notify` | `SLACK_BOT_TOKEN` (when `SLACK_NOTIFIER=http`) | outbox → `chat.postMessage` |
| `incidentpilot-worker` (general / AI) | **no** Slack token | LLM + orchestration only |

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
| `SLACK_NOTIFIER` | `fake` | `fake` / `http` |
| `SLACK_BOT_TOKEN` | — | required for `http`; notify process only |
