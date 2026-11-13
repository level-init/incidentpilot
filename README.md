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
| [docs/scenarios.md](docs/scenarios.md) | Scenario runner (N1): baseline gate, FAILED vs scored |
| [docs/ground-truth.md](docs/ground-truth.md) | Evaluator-only GroundTruth schema + isolation (N2) |
| [docs/eval-metrics.md](docs/eval-metrics.md) | Operational metric formulas + RootCauseMatchSpec (N5) |
| [docs/operational-evaluation.md](docs/operational-evaluation.md) | Immutable OperationalEvaluation pin at RESOLVED (N6) |
| [docs/postmortem-evaluation.md](docs/postmortem-evaluation.md) | PostmortemEvaluation pin at CLOSED + eval family (N7) |
| [docs/isolation.md](docs/isolation.md) | Isolation-integrity suite — GT never in investigation path (N8) |
| [docs/sim-baseline.md](docs/sim-baseline.md) | Sim health/ready baseline contract (E4) |
| [docs/git-standards.md](docs/git-standards.md) | Branching, commits, PRs (`main` / `dev`) |
| [docs/repo-layout.md](docs/repo-layout.md) | Monorepo packages ↔ deployables |
| [docs/local-compose.md](docs/local-compose.md) | Compose profiles (`core` / `evidence` / `simulation` / `full`) |
| [docs/db.md](docs/db.md) | Postgres schemas, roles, migrations, GT isolation |
| [docs/outbox.md](docs/outbox.md) | Transactional outbox + idempotency semantics |
| [docs/command-layer.md](docs/command-layer.md) | Shared domain commands (API + workers) |
| [docs/api.md](docs/api.md) | HTTP API local curl examples |
| [docs/alert-webhooks.md](docs/alert-webhooks.md) | Alert ingest: AM webhook (F1/F2) + CW adapter (F3) |
| [docs/evidence.md](docs/evidence.md) | Evidence producers + fingerprint dedup (G1) |
| [docs/auth.md](docs/auth.md) | Session identity (stub → OIDC contract) |
| [docs/temporal-queues.md](docs/temporal-queues.md) | Temporal task queues + Freeze-9 consumers |
| [openapi/openapi.json](openapi/openapi.json) | Published HTTP OpenAPI contract |

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
| `make compose-core` | Start `core` infra (Postgres, Temporal, local S3 + buckets) |
| `make compose-full` | Start all profiles (includes optional Redis) |
| `make compose-down` | Stop compose services |
| `make compose-config` | Validate compose YAML for `PROFILE` (default `core`) |
| `make migrate` | Apply SQL migrations (`domain` / `scenarios` / `eval` + roles) |
| `make db-verify-isolation` | Prove GroundTruth denied for `ip_app` / `ip_runner` |
| `make test-isolation` | N8 isolation suite (static + pytest + sim contract); required for scored runs |
| `make verify-local-infra` | Temporal UI + local S3 put/get smoke |
| `make temporal-queue-smoke` | Workers subscribe to general / evidence / remediation |
| `make sim-happy-path` | Curl sim-gateway checkout happy path (`:8100`) |
| `make sim-contract-scan` | Fail if sim exposes GT / root-cause cheat routes |
| `make test-sim-contract` | Contract pytest + scan (E6; CI `sim-contract` job) |
| `make sim-baseline-gate` | All sim `/healthz` + gateway `/readyz` |
| `make sim-traffic` | Baseline load (`DURATION=60` `RPS=1`) |
| `make sim-inject` | Fault injectors (`ARGS='activate bad_deploy'`) |
| `make obs-smoke` | Prom / Loki / Tempo / Grafana / Alertmanager health |
| `make openapi-export` | Write `openapi/openapi.json` from FastAPI app |
| `make api-run` | Run local API on :8000 (`Bearer local-dev`) |
| `make web-dev` | Next.js dashboard on :3000 (M1; needs API) |

### Compose profiles

```bash
cp .env.example .env    # optional; never commit .env
make compose-core       # postgres + temporal + local S3 (Silo) + bucket init
docker compose --profile core --profile redis up -d   # optional cache
make compose-up PROFILE=evidence
make compose-full
```

Details and local ports: [docs/local-compose.md](docs/local-compose.md).
DB roles / GT isolation: [docs/db.md](docs/db.md). Tool config: `pyproject.toml`.

```bash
make compose-core
make migrate
make db-verify-isolation
make verify-local-infra
```

