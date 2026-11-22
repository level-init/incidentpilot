# Swap the demo app for your system (Q6 / #298)

**Removable** means leave the Compose `simulation` profile **off** — not delete
half the monorepo. IncidentPilot (`core` + API/workers/`web`) stays; the bundled
demo world is optional sample content ([demo-app.md](demo-app.md)).

```text
Before (local demo):   simulation/  -->  IncidentPilot
After  (your stack):   your apps    -->  Alertmanager / Slack  -->  IncidentPilot
```

## Checklist

### 1. Run IncidentPilot without simulation

```bash
# Do NOT start PROFILE=simulation or compose-full unless you want the demo app
make compose-core
make migrate
make api-run
# general worker + optional evidence/remediation as needed — see quickstart.md
```

Confirm no sim ports if you want a clean slate:

```bash
# should fail / connection refused if simulation is down
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8100/healthz || true
```

### 2. Keep using the same IP contracts

Your systems talk to IncidentPilot the **same way** the demo did — via providers,
not by embedding the Python monorepo in your app:

| Signal | How to wire |
| --- | --- |
| Alerts | Alertmanager → `POST /webhooks/alerts/alertmanager` |
| Human approvals / ChatOps | Slack → `/webhooks/slack/interactions` + `/commands` |
| Operators | Product UI (`web/`) + session/OIDC |

Full recipes: [connect-your-stack.md](connect-your-stack.md).

### 3. Minimum signals that make IP useful

You do not need every collector on day one. A useful minimum:

1. **Firing alerts** with stable labels (`alertname`, `service` or equivalent)  
2. **Webhook auth** configured (`ALERTMANAGER_WEBHOOK_TOKEN` or basic/header)  
3. **API + general worker** up so incidents progress in Temporal  

Nice to have later: Prom/Loki/Tempo URLs on the **evidence** worker, Slack bot
for outbound threads, BYO Gemini on the general worker ([llm.md](llm.md)).

### 4. Optional: evidence profile without simulation

You can run local Prom/AM/Grafana for **your** scrape configs without the demo
microservices:

```bash
make compose-core
make compose-up PROFILE=evidence
# Point Prometheus at your targets; point AM receiver at localhost:8000
# (see connect-your-stack.md)
```

Or skip Compose `evidence` entirely and use your existing observability stack —
only the webhook (and optional Slack) must reach IncidentPilot.

### 5. What you can ignore in the repo

| Path | When swapping |
| --- | --- |
| `simulation/` | Leave unstarted; no need to delete |
| `make sim-*` / scored `make scenario` | Demo/eval paths; optional |
| Compose `full` | Includes simulation — avoid if you only want IP + your apps |

You still use: `api/`, `worker/`, `web/`, `shared/`, `adapters/`, docs, Helm/Terraform when ready.

## Verify

```bash
# IP up, no sim required
curl -s http://localhost:8000/healthz

# Your AM (or curl) creates an incident
curl -s -X POST http://localhost:8000/webhooks/alerts/alertmanager \
  -H "authorization: Bearer $ALERTMANAGER_WEBHOOK_TOKEN" \
  -H 'content-type: application/json' \
  -H 'idempotency-key: swap-1' \
  -d '{"receiver":"incidentpilot","status":"firing","alerts":[{"status":"firing","labels":{"alertname":"FromMyApp","service":"my-service"},"annotations":{"summary":"swap-your-app"}}]}'

curl -s -H 'Authorization: Bearer local-dev' http://localhost:8000/incidents | head -c 500
```

## Related

| Doc | Role |
| --- | --- |
| [demo-app.md](demo-app.md) | What the bundled sample system is |
| [connect-your-stack.md](connect-your-stack.md) | AM + Slack recipes |
| [quickstart.md](quickstart.md) | First local incident (often with or without sim) |
| [local-compose.md](local-compose.md) | Profile reference |
