# Quickstart — first incident in ~30 minutes (Q1 / #292)

**Goal:** clone IncidentPilot, bring up local infra, post one alert, see an
incident. No AWS bill. No shared API keys.

**Model:** you **self-host**. The bundled `simulation/` services are an optional
**demo app** you can leave off and replace with your own stack later
([swap guide — Q6](https://github.com/level-init/incidentpilot/issues/298)).

## Prerequisites

| Need | Notes |
| --- | --- |
| Python 3.12+ | `make bootstrap` |
| Docker + Compose | Postgres, Temporal, local S3 |
| ~8 GB RAM free | Comfortable for `core` + API |

Optional later: Node 20+ for the web UI; a personal Gemini key for live LLM.

## 1. Clone and bootstrap (~5 min)

```bash
git clone git@github.com:level-init/incidentpilot.git
cd incidentpilot
git checkout dev

cp .env.example .env          # never commit .env
make bootstrap                # .venv + deps
```

Default LLM is **fake** (no key required). To use **your** Gemini key later, see
[§6](#6-optional-your-gemini-key-q7).

## 2. Infra + database (~5 min)

```bash
make compose-core             # Postgres, Temporal (+ UI), MinIO/S3
make migrate
make verify-local-infra       # Temporal UI + S3 smoke
```

| Check | URL |
| --- | --- |
| Temporal UI | http://localhost:8088 |
| Postgres | `localhost:5432` (see `.env`) |

Compose profiles: [local-compose.md](local-compose.md).

## 3. API (and workers) (~5 min)

In one terminal:

```bash
make api-run                  # http://localhost:8000
```

In another (so alerts can start workflows):

```bash
# general worker — orchestration + optional LLM
PYTHONPATH=worker:shared:adapters:.venv/lib/python*/site-packages \
  .venv/bin/python -m incidentpilot_worker
```

Stub auth (local only): `Authorization: Bearer local-dev` —
[auth.md](auth.md).

Health:

```bash
curl -s http://localhost:8000/healthz
```

## 4. Create your first incident (~2 min)

Uses the Alertmanager webhook (F1). Token from `.env.example`
(`ALERTMANAGER_WEBHOOK_TOKEN=dev-am-webhook-token`):

```bash
curl -s -X POST http://localhost:8000/webhooks/alerts/alertmanager \
  -H 'authorization: Bearer dev-am-webhook-token' \
  -H 'content-type: application/json' \
  -H 'idempotency-key: quickstart-1' \
  -d '{
    "receiver": "incidentpilot",
    "status": "firing",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "SimHighErrorRate",
        "service": "payment"
      },
      "annotations": {
        "summary": "quickstart demo alert"
      }
    }]
  }'
```

Expect **202** with `incident_ids`. Then:

```bash
curl -s -H 'Authorization: Bearer local-dev' http://localhost:8000/incidents \
  | python -m json.tool | head -80
```

You should see a DETECTED (or further) incident for `payment`.

Details: [alert-webhooks.md](alert-webhooks.md).

## 5. Optional — dashboard + demo app

**Web UI** (another terminal):

```bash
make web-dev                  # http://localhost:3000 — Bearer local-dev in UI
```

**Bundled demo app** (`simulation/` — optional sample system, not your prod app):

```bash
make compose-up PROFILE=simulation
# or fuller telemetry path:
docker compose --profile evidence --profile simulation up -d
make sim-happy-path
```

See [demo-app.md](demo-app.md). Faults / scored scenarios: [scenarios.md](scenarios.md),
[sim-faults.md](sim-faults.md). Simulation is **not** required for §4.

## 6. Optional — your Gemini key (Q7)

Live reasoning on the **general worker only** (never evidence/remediation):

```bash
# in .env — use YOUR key; never commit
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash
LLM_API_KEY=your-key-here
# or: GEMINI_API_KEY=your-key-here
```

Restart the general worker after editing `.env`. CI and default clone stay on
`LLM_PROVIDER=fake`. Full notes: [llm.md](llm.md).

## 7. What next

| Goal | Doc / issue |
| --- | --- |
| Point **your** Alertmanager / Slack at IP | [connect-your-stack.md](connect-your-stack.md) (Q2) |
| Turn off simulation; wire your system | [swap-your-app.md](swap-your-app.md) (Q6) |
| K8s chart locally | [helm-kind.md](helm-kind.md) |
| Ephemeral AWS staging (optional $) | [staging-eks.md](staging-eks.md) |

## Troubleshooting

| Symptom | Likely fix |
| --- | --- |
| Webhook **503** | Set `ALERTMANAGER_WEBHOOK_TOKEN` in `.env`; restart API |
| Webhook **401** | Wrong bearer; use `dev-am-webhook-token` from `.env.example` |
| Webhook **202** but empty `/incidents` | API DB URL / migrations; re-run `make migrate` |
| Incident stuck DETECTED | Start general worker; check Temporal UI :8088 |
| `pytest` / tools missing | Use `.venv/bin/…` or `make bootstrap` |
| Gemini `RuntimeError` | Set `LLM_API_KEY` or stay on `LLM_PROVIDER=fake` |
| Port conflicts | `make compose-down`; free 5432/7233/8000/8088 |

## Cleanup

```bash
make compose-down
```
