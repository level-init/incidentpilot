# Local Docker Compose

Profiles match the product overview environments for shared local DX.

| Profile | What starts |
| --- | --- |
| `core` | Postgres, Temporal (+ UI), Silo/S3 (+ bucket bootstrap) |
| `redis` | Optional cache-only Redis (never authoritative) |
| `evidence` | Prometheus, Loki, Tempo, Grafana, Alertmanager, Promtail (E3) |
| `simulation` | Demo microservices (gateway/auth/checkout/payment/inventory/notification) |
| `full` | core + redis + evidence + simulation |

## Quick start

```bash
cp .env.example .env   # optional overrides; do not commit .env

make compose-core      # postgres + temporal + local S3
make migrate
make verify-local-infra
make compose-ps
make compose-down
```

Optional Redis (cache only):

```bash
docker compose --profile core --profile redis up -d
# or
make compose-up PROFILE=redis   # redis alone; usually pair with core
```

Other profiles:

```bash
make compose-up PROFILE=evidence     # Prom/Loki/Tempo/Grafana/AM
make compose-up PROFILE=simulation   # sim microservices on :8100–:8105
# Prefer both together so Prom scrapes sim /metrics and Tempo gets OTLP:
docker compose --profile evidence --profile simulation up -d
make sim-happy-path
make obs-smoke
make sim-contract-scan
make compose-full
```

Validate without starting containers:

```bash
docker compose --profile core config
```

## Local endpoints (core)

| Service | URL / port | Local credentials |
| --- | --- | --- |
| Postgres | `localhost:5432` | user/db/password from `.env.example` (default `incidentpilot`) |
| Temporal gRPC | `localhost:7233` | no auth locally |
| Temporal UI | http://localhost:8088 | — |
| S3 API (Silo) | http://localhost:9000 | `minioadmin` / `minioadmin` (override via env) |
| S3 console | http://localhost:9001 | same as API |
| Redis (optional) | `localhost:6379` | no auth; enable with `--profile redis` |
| Sim gateway | http://localhost:8100 | `POST /v1/checkout` happy path |
| Sim auth…notification | `8101`–`8105` | see [../simulation/README.md](../simulation/README.md) |
| Grafana | http://localhost:3000 | `admin` / `admin` (override via env) |
| Prometheus | http://localhost:9090 | — |
| Alertmanager | http://localhost:9093 | `GET /-/healthy`, `GET /api/v2/status` |
| Loki | http://localhost:3100 | — |
| Tempo | http://localhost:3200 | OTLP `:4317` gRPC / `:4318` HTTP |

### Local S3 buckets (created by `minio-init`)

| Bucket | Env override | Use |
| --- | --- | --- |
| `incidentpilot-evidence` | `S3_BUCKET_EVIDENCE` | Raw evidence blobs |
| `incidentpilot-ai-artifacts` | `S3_BUCKET_AI_ARTIFACTS` | AIInvocation artifacts |

Postgres also creates empty `temporal` and `temporal_visibility` databases on first boot
(`deploy/compose/postgres/init/`). After `make compose-core`, run `make migrate` for
`domain` / `scenarios` / `eval` schemas and roles — see [db.md](db.md).

**Why Silo, not `minio/minio`?** MinIO Community Edition container images were removed from
Docker Hub. `pgsty/silo` speaks the same S3/MinIO API and env vars for local Compose;
production-demo still targets real S3.

## Health / smoke checks

Containers expose Docker healthchecks for Postgres, Temporal, Temporal UI, Silo, Redis,
and the evidence-profile obs services. App-level smoke:

```bash
make verify-local-infra
# Temporal UI HTTP 200
# Silo /minio/health/live
# aws-cli put/get on incidentpilot-evidence

make temporal-queue-smoke
# workers subscribe to incidentpilot-general / -evidence / -remediation

make obs-smoke
# Alertmanager + Prometheus + Loki + Tempo + Grafana (+ sim-traffic dashboard)
```

Configs live under `deploy/compose/observability/`. Grafana ships a provisioned
**Simulation traffic** dashboard (`uid=sim-traffic`) for request/error/latency rates.

Task queue names and Freeze-9 consumer mapping: [temporal-queues.md](temporal-queues.md).

## Secrets

- Defaults are **local-only** and documented in `.env.example`.
- Copy to `.env` for overrides; `.env` is gitignored.
- Never commit real cloud credentials into Compose files.
