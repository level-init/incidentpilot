# Demo app — bundled simulation (Q5 / #297)

IncidentPilot ships with a **sample distributed system** under `simulation/`.
It exists so you can demo faults → alerts → incidents **without** wiring your
production apps on day one.

It is **not** part of a production IncidentPilot deploy. Adopters run IP
(`core`) against **their** stack; simulation is optional Compose profile
content. To swap it out: Q6 ([#298](https://github.com/level-init/incidentpilot/issues/298)).

```text
[ simulation/  = demo app ]  --telemetry / AM-->  [ IncidentPilot ]
[ your services = real app ] --same contracts-->  [ IncidentPilot ]
```

## Compose profiles

| Profile | What runs | Use when |
| --- | --- | --- |
| `core` | Postgres, Temporal, local S3 | Always — IP data plane |
| `simulation` | gateway / auth / checkout / payment / inventory / notification | Demo app only |
| `evidence` | Prom / Loki / Tempo / Grafana / Alertmanager | Telemetry path for sim (or your scrapers) |
| `full` | core + redis + evidence + simulation | Kitchen-sink local demo |
| `redis` | Optional cache | Never required for SoR |

```bash
# Product infra only (no demo app)
make compose-core

# Demo app (sim microservices on :8100–:8105)
make compose-up PROFILE=simulation

# Demo app + observability (recommended for fault → alert demos)
docker compose --profile evidence --profile simulation up -d
```

Details: [local-compose.md](local-compose.md).

## What the demo app is

Six services that behave like a small commerce stack:

| Service | Port | Role |
| --- | --- | --- |
| gateway | 8100 | Checkout orchestration |
| auth | 8101 | Session validate |
| checkout | 8102 | Orders |
| payment | 8103 | Charges |
| inventory | 8104 | Stock |
| notification | 8105 | Outbound messages |

Package docs: [simulation/README.md](../simulation/README.md).

Happy path:

```bash
make sim-happy-path
# or:
curl -s -X POST http://localhost:8100/v1/checkout \
  -H 'content-type: application/json' \
  -d '{"user_id":"user_demo","token":"tok_demo_user","sku":"SKU-WIDGET","quantity":1}'
```

## Faults (break the demo on purpose)

Eight injectors change **service behavior** only (errors, latency, queues).
They do **not** plant GroundTruth or fake Evidence into IncidentPilot.

```bash
make sim-inject ARGS='list'
make sim-inject ARGS='activate bad_deploy'
make sim-inject ARGS='reset'
```

Catalog: [sim-faults.md](sim-faults.md). Scored end-to-end paths:
[scenarios.md](scenarios.md).

## How this relates to IncidentPilot

1. Run `core` + API/workers ([quickstart](quickstart.md)).  
2. Optionally start `simulation` (+ `evidence`).  
3. Inject a fault **or** POST a sample AM webhook.  
4. Investigate in the **product** UI (`web/`) — not in the sim services.

Sim must never expose GT cheat routes — [sim-contract.md](sim-contract.md).

## Included demo app vs your app

| | Demo app (`simulation/`) | Your app |
| --- | --- | --- |
| Ships in this repo | Yes | No |
| Required to run IP | **No** | — |
| Wire via | Compose profile | Your Alertmanager / Slack → [connect-your-stack.md](connect-your-stack.md) |
| In production IP install | Leave **off** | Point providers at your IP |

## Related

- Quickstart: [quickstart.md](quickstart.md)  
- Connect providers: [connect-your-stack.md](connect-your-stack.md)  
- Baseline / traffic: [sim-baseline.md](sim-baseline.md)  
