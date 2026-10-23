# Local Docker Compose

Profiles match the product overview environments for shared local DX.

| Profile | What starts |
| --- | --- |
| `core` | Postgres, Temporal (+ UI), Silo/S3 (+ bucket bootstrap) |
| `redis` | Optional cache-only Redis (never authoritative) |
| `evidence` | Placeholder until Epic E/G (Prom / Loki / Tempo / AM) |
| `simulation` | Placeholder until Epic E (demo microservices) |
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
make compose-up PROFILE=evidence
make compose-up PROFILE=simulation
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

Containers expose Docker healthchecks for Postgres, Temporal, Temporal UI, Silo, and Redis.
App-level smoke:

```bash
make verify-local-infra
# Temporal UI HTTP 200
# Silo /minio/health/live
# aws-cli put/get on incidentpilot-evidence

make temporal-queue-smoke
# workers subscribe to incidentpilot-general / -evidence / -remediation
```

Task queue names and Freeze-9 consumer mapping: [temporal-queues.md](temporal-queues.md).

## Secrets

- Defaults are **local-only** and documented in `.env.example`.
- Copy to `.env` for overrides; `.env` is gitignored.
- Never commit real cloud credentials into Compose files.
