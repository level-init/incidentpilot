# Local Docker Compose

Profiles match the product overview environments for shared local DX.

| Profile | What starts |
| --- | --- |
| `core` | Postgres, Temporal (+ UI), local S3 (Silo / MinIO-API), Redis (cache-only) |
| `evidence` | Placeholder until Epic E/G (Prom / Loki / Tempo / AM) |
| `simulation` | Placeholder until Epic E (demo microservices) |
| `full` | All of the above |

## Quick start

```bash
cp .env.example .env   # optional overrides; do not commit .env

make compose-core      # or: docker compose --profile core up -d
make compose-ps
make compose-down
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
| Redis | `localhost:6379` | no auth; cache-only |

Postgres also creates empty `temporal` and `temporal_visibility` databases on first boot
(`deploy/compose/postgres/init/`). After `make compose-core`, run `make migrate` for
`domain` / `scenarios` / `eval` schemas and roles — see [db.md](db.md).
Bucket bootstrap lands in #5 (A6) if needed.

**Why Silo, not `minio/minio`?** MinIO Community Edition container images were removed from
Docker Hub. `pgsty/silo` speaks the same S3/MinIO API and env vars for local Compose;
production-demo still targets real S3.

## Secrets

- Defaults are **local-only** and documented in `.env.example`.
- Copy to `.env` for overrides; `.env` is gitignored.
- Never commit real cloud credentials into Compose files.
