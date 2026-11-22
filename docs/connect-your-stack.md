# Connect your stack (Q2 / #293)

IncidentPilot is **self-hosted**. You do **not** embed it inside your Next/Rails
app. You point **your** Alertmanager (and optional Slack app) at **your** IP
instance using the same HTTP contracts.

```text
Your apps / Prometheus  →  Alertmanager  →  POST /webhooks/alerts/…  →  IncidentPilot
Humans (browser)        →  UI / API (session or OIDC)
Slack                   →  POST /webhooks/slack/…  (signing secret)
```

Bundled `simulation/` is only a **sample** system for demos —
[demo-app.md](demo-app.md), [quickstart](quickstart.md). To drop it and use
production apps later, see Q6
([#298](https://github.com/level-init/incidentpilot/issues/298)).

## Auth split (do not mix)

| Traffic | Where | Auth |
| --- | --- | --- |
| Humans (UI + user API) | user / API host | Session Bearer or OIDC — [auth.md](auth.md), [ingress.md](ingress.md) |
| Alertmanager / Slack / GitHub | **webhooks** host or path | Provider secrets only — **no** OIDC in front |

On Kubernetes, Helm renders separate Ingresses (`user` vs `webhooks`). Locally,
both hit `http://localhost:8000` but **still** use different auth mechanisms.

## Env cheat sheet

| Var | Process | Purpose |
| --- | --- | --- |
| `ALERTMANAGER_WEBHOOK_TOKEN` | api | Bearer for AM webhook (or basic/header — see below) |
| `SLACK_SIGNING_SECRET` | api **only** | Verify Slack interactions + slash commands |
| `SLACK_BOT_TOKEN` | notify worker only | Outbound posts when `SLACK_NOTIFIER=http` |
| `SLACK_NOTIFIER` | notify | `fake` (default) / `http` |
| `SLACK_COMMAND_RESPONDERS` | api | Slack user ids allowed to mutate via `/ip` |
| `SLACK_COMMANDS_OPEN` | api | `1` = local/demo allow all mutators |
| `INCIDENTPILOT_WEB_BASE_URL` | workers | Deep links in Slack messages |
| `LLM_PROVIDER` / `LLM_API_KEY` | general worker | Optional BYO Gemini — [llm.md](llm.md), [quickstart](quickstart.md#6-optional-your-gemini-key-q7) |

Never put `SLACK_SIGNING_SECRET` or bot tokens on the general AI worker
([slack.md](slack.md) privilege split).

## 1. Alertmanager → IncidentPilot

### Endpoint

```http
POST /webhooks/alerts/alertmanager
Authorization: Bearer <ALERTMANAGER_WEBHOOK_TOKEN>
Content-Type: application/json
```

Local default token: `dev-am-webhook-token` (`.env.example`). At least one of
bearer / basic / custom header must be set or the route returns **503**.
Details: [alert-webhooks.md](alert-webhooks.md).

### Receiver snippet

```yaml
# alertmanager.yml — point at YOUR IncidentPilot API
route:
  receiver: incidentpilot
  group_by: ["alertname", "service"]

receivers:
  - name: incidentpilot
    webhook_configs:
      - url: http://HOST:8000/webhooks/alerts/alertmanager
        # Docker network example: http://host.docker.internal:8000/...
        # K8s webhooks Ingress: https://hooks.example.com/webhooks/alerts/alertmanager
        http_config:
          authorization:
            type: Bearer
            credentials: YOUR_ALERTMANAGER_WEBHOOK_TOKEN
```

### Smoke (local)

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/webhooks/alerts/alertmanager \
  -H 'content-type: application/json' \
  -d '{"receiver":"x","status":"firing","alerts":[]}'
# → 401 without token

curl -s -X POST http://localhost:8000/webhooks/alerts/alertmanager \
  -H 'authorization: Bearer dev-am-webhook-token' \
  -H 'content-type: application/json' \
  -H 'idempotency-key: connect-am-1' \
  -d '{"receiver":"incidentpilot","status":"firing","alerts":[{"status":"firing","labels":{"alertname":"HighErrorRate","service":"checkout"},"annotations":{"summary":"connect-your-stack"}}]}'
# → 202
```

Compose profile `evidence` runs a local Alertmanager (:9093) for the sim world;
production AM is whatever you already operate.

## 2. Slack → IncidentPilot

### URLs to paste in the Slack app

| Slack feature | Request URL |
| --- | --- |
| Interactivity (buttons) | `https://<webhooks-host>/webhooks/slack/interactions` |
| Slash command `/ip` | `https://<webhooks-host>/webhooks/slack/commands` |

Local (Slack needs a public URL — use a tunnel for real Slack, or keep
`SLACK_NOTIFIER=fake` and use API/UI only):

```text
https://<your-tunnel>/webhooks/slack/interactions
https://<your-tunnel>/webhooks/slack/commands
```

### App checklist

1. Create a Slack app in your workspace  
2. **Signing Secret** → `SLACK_SIGNING_SECRET` on **api** only  
3. Enable Interactivity → interactions URL above  
4. Create slash command `/ip` → commands URL above  
5. (Outbound) Bot token → `SLACK_BOT_TOKEN` on the **notify** process;
   set `SLACK_NOTIFIER=http`  
6. For demos: `SLACK_COMMANDS_OPEN=1`; for real: set `SLACK_COMMAND_RESPONDERS`

Full behavior: [slack.md](slack.md).

### Privilege reminder

| Process | May hold |
| --- | --- |
| `incidentpilot-api` | `SLACK_SIGNING_SECRET` |
| `python -m incidentpilot_worker notify` | `SLACK_BOT_TOKEN` |
| general / evidence / remediation workers | **neither** Slack secret |

## 3. Humans still use the product UI

- Dashboard: `make web-dev` → http://localhost:3000  
- API session: `Authorization: Bearer local-dev` (stub) — [auth.md](auth.md)  
- Do **not** put AM or Slack traffic behind oauth2-proxy / OIDC

## 4. Kubernetes hosts (when you leave Compose)

| Host role | Example | Auth |
| --- | --- | --- |
| User UI / API | `app.` / `api.` | OIDC |
| Webhooks | `hooks.` | AM token / Slack HMAC only |

See [ingress.md](ingress.md).

## Related

| Doc | Role |
| --- | --- |
| [quickstart.md](quickstart.md) | First incident without Slack |
| [demo-app.md](demo-app.md) | Bundled simulation as optional sample system |
| [alert-webhooks.md](alert-webhooks.md) | AM auth, replay, correlation |
| [slack.md](slack.md) | Inbound verify, ChatOps, notifier |
| [ingress.md](ingress.md) | User vs webhooks Ingress split |
| [llm.md](llm.md) | BYO Gemini on general worker |
