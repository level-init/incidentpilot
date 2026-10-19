# IncidentPilot

**IncidentPilot** is an evidence-driven production incident-response platform.
When an alert fires, it gathers telemetry and change history, forms competing
hypotheses with citations, retrieves runbooks, estimates impact, coordinates
response (Slack + dashboard), and can remediate only through
**policy + approval + a reserved execution attempt**—then validates recovery
and produces an evidence-grounded postmortem.

It is built as a **portfolio / production-style demo**: a simulated distributed
system plus IncidentPilot, with reproducible scenario evaluation. 

## Documentation

| Doc | Purpose |
| --- | --- |
| [docs/product-overview.md](docs/product-overview.md) | Product goal, closed loop, locked design decisions |
| [docs/git-standards.md](docs/git-standards.md) | Branching, commits, PRs (`main` / `dev`) |
| [docs/repo-layout.md](docs/repo-layout.md) | Monorepo packages ↔ deployables |
| [docs/local-compose.md](docs/local-compose.md) | Compose profiles (`core` / `evidence` / `simulation` / `full`) |
| [docs/db.md](docs/db.md) | Postgres schemas, roles, migrations, GT isolation |

## Repository layout

| Path | Deployable / role |
| --- | --- |
| `api/` | `incidentpilot-api` (FastAPI) |
| `worker/` | `incidentpilot-worker` (Temporal + reasoning) |
| `remediation_worker/` | privileged remediation execute |
| `web/` | `incidentpilot-web` dashboard |
| `shared/` | shared domain library |
| `adapters/` | outbound integrations |
| `simulation/` | demo microservices |
| `scenario_runner/` | scenario runner (no GroundTruth) |
| `evaluator/` | evaluator (GroundTruth-isolated) |

Details: [docs/repo-layout.md](docs/repo-layout.md).

## Stack (summary)

| Layer | Choice |
| --- | --- |
| API / workers | Python, FastAPI |
| Workflow | Temporal |
| Domain DB | PostgreSQL (+ pgvector / FTS) |
| Blobs | S3 (MinIO locally) |
| Cache | Redis optional (cache only) |
| Local | Docker Compose |
| Cloud demo | AWS EKS, RDS, S3, Secrets Manager |
| Observability | Prometheus, Alertmanager, Grafana, Loki, OpenTelemetry / Tempo |
| Integrations | Slack, GitHub (read), Alertmanager (+ CloudWatch later) |

Details and non-negotiables live in [docs/product-overview.md](docs/product-overview.md).

## Repository workflow

- Long-lived branches: `main` (always shippable), `dev` (integration)
- All work: **GitHub issue → task branch from `dev` → PR into `dev`**
- Ship verified slices: **PR `dev` → `main`**

See [docs/git-standards.md](docs/git-standards.md).

## Local development

Requires **Python 3.12+**.

```bash
git clone git@github.com:level-init/incidentpilot.git
cd incidentpilot
git checkout dev

make bootstrap   # creates .venv + installs ruff, mypy, pytest
make lint        # ruff check + format check + mypy
make test        # pytest smoke imports
make format      # auto-fix lint + format (optional)
```

| Target | Purpose |
| --- | --- |
| `make bootstrap` | Create `.venv` and install `requirements-dev.txt` |
| `make lint` | Ruff lint + format check + mypy |
| `make format` | Apply ruff fixes / format |
| `make typecheck` | mypy only |
| `make test` | pytest (scaffold smoke tests for now) |
| `make compose-core` | Start `core` infra (Postgres, Temporal, local S3, Redis) |
| `make compose-full` | Start all profiles |
| `make compose-down` | Stop compose services |
| `make compose-config` | Validate compose YAML for `PROFILE` (default `core`) |
| `make migrate` | Apply SQL migrations (`domain` / `scenarios` / `eval` + roles) |
| `make db-verify-isolation` | Prove GroundTruth denied for `ip_app` / `ip_runner` |

### Compose profiles

```bash
cp .env.example .env    # optional; never commit .env
make compose-core       # postgres + temporal + local S3 (Silo) + redis
make compose-up PROFILE=evidence
make compose-full
```

Details and local ports: [docs/local-compose.md](docs/local-compose.md).
DB roles / GT isolation: [docs/db.md](docs/db.md). Tool config: `pyproject.toml`.

```bash
make compose-core
make migrate
make db-verify-isolation
```

## Status

Foundation in progress through A5 (schemas/roles). Next: Temporal/MinIO hardening (#5),
then domain entities (Epic B).
