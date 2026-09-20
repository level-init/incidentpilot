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

Local Compose profiles and `make` targets will land with the platform foundation.
Until then:

```bash
git clone git@github.com:level-init/incidentpilot.git
cd incidentpilot
git checkout dev
```

## Status

Early stage: documentation and collaboration standards first; implementation
follows the product overview’s build order (simulator-first vertical, then
widen).
