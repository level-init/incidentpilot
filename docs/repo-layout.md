# Repository layout

Top-level packages map 1:1 to the deployables in
[product-overview.md](product-overview.md). This ticket (#1 / A2) only scaffolds
folders and placeholders—no business domain logic.

```text
incidentpilot/
├── api/                    # incidentpilot-api (FastAPI HTTP + webhooks)
├── worker/                 # incidentpilot-worker (Temporal + reasoning)
├── remediation_worker/     # remediation-worker (privileged execute only)
├── web/                    # incidentpilot-web (ops dashboard)
├── shared/                 # shared domain library (API + workers import this)
├── adapters/               # outbound integrations (Slack, GitHub, K8s, …)
├── simulation/             # demo microservices + local world
├── scenario_runner/        # scenario runner (isolated from investigation)
├── evaluator/              # evaluator (GroundTruth-only; isolated)
├── deploy/                 # compose, db init, k8s RBAC (J11) / charts (O*)
├── docs/                   # product + git standards + this file
└── .github/                # GitHub Actions / project metadata
```

## Python packages

| Directory | Import package | Role |
| --- | --- | --- |
| `api/` | `incidentpilot_api` | Short-lived HTTP / webhooks (incl. AM `/webhooks/alerts`) |
| `worker/` | `incidentpilot_worker` | Temporal activities + reasoning (no rollback keys, no GT) |
| `remediation_worker/` | `incidentpilot_remediation` | Privileged remediation execute / reconcile |
| `shared/` | `incidentpilot_shared` | Domain types, commands, shared utilities |
| `adapters/` | `incidentpilot_adapters` | External system clients behind stable interfaces |
| `scenario_runner/` | `incidentpilot_scenario_runner` | Injects faults / traffic; never reads GroundTruth answers |
| `evaluator/` | `incidentpilot_evaluator` | Scores ScenarioRuns; only process that may read GroundTruth |

Import convention: packages use the `incidentpilot_*` prefix so names stay
unambiguous when installed editable (tooling lands in #2 / A3).

## Web

`web/` holds the dashboard. Framework choice is deferred to the UI epic (M1);
this folder is reserved so deployable layout is stable from day one.

## Simulation

`simulation/` holds the demo services (gateway, auth, checkout, payment,
inventory, notification) from issue #26 (E1). Compose profile `simulation`
exposes them on ports `8100`–`8105`. Baseline traffic generator lives under
`simulation/traffic/` (E4); contract: [sim-baseline.md](sim-baseline.md).
Fault injectors: `simulation/faults/` + `common/faults.py` (E5);
[sim-faults.md](sim-faults.md). GT isolation contract: [sim-contract.md](sim-contract.md).

## Observability (local)

`deploy/compose/observability/` holds Prometheus / Loki / Tempo / Grafana /
Alertmanager / Promtail configs for compose profile `evidence` (E3 / #28).

## Isolation rules (layout reminder)

- `evaluator/` must not be imported by `api/`, `worker/`, or `remediation_worker/`.
- `scenario_runner/` must not embed GroundTruth answer keys.
- `remediation_worker/` is the only package expected to hold privileged execute credentials.
