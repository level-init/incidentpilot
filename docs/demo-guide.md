# Demo guide — bad-deployment scored path (P8 / #134)

Portfolio demo someone else can follow. Primary path: **scored
`bad-deployment`** (N9) with the Level-2 approval harness (no Slack required).
For a shorter “first alert” path, use [quickstart.md](quickstart.md).

**Audience:** engineers cloning the product repo. Marketing site is out of
scope here (Q3 sibling repo).

## What you will show

1. Isolation gate green (GroundTruth stays out of the investigation path)  
2. Faulty **demo app** (`simulation/`) — optional for scored harness; required
   for live inject demos  
3. Scored vertical: propose → `REQUIRE_APPROVAL` → harness approve → resolve  
4. Dual-stage eval pin (`make eval`)  
5. Optional: open product UI / eval pages  

Runtime is typically **15–25 minutes** after images/deps are warm.

## Prerequisites

```bash
git clone git@github.com:level-init/incidentpilot.git
cd incidentpilot
git checkout dev
cp .env.example .env    # never commit
make bootstrap
```

| Need | Why |
| --- | --- |
| Docker Compose | Postgres / Temporal / S3 (`core`); sim for live world |
| Python 3.12 + `.venv` | `make scenario` / `make eval` |
| `LLM_PROVIDER=fake` | Default — deterministic demo; optional Gemini later ([byo-llm.md](byo-llm.md)) |

## Scripted path (recommended)

One command runs checks + scored bad-deploy + eval:

```bash
make demo-bad-deploy
# or: ./scripts/demo_bad_deploy.sh
```

The script:

1. Ensures Compose `core` is up (starts it if needed)  
2. Runs `make migrate`  
3. Runs `make test-isolation` (required before scored runs)  
4. Runs `make scenario NAME=bad-deployment`  
5. Runs `make eval`  
6. Prints where to look next (API tokens, UI, other scenarios)  

Skip isolation if you just re-ran it: `SKIP_ISOLATION=1 make demo-bad-deploy`.

## Manual path (same steps)

```bash
make compose-core
make migrate

# Required before scored verticals (N8)
make test-isolation

# Scored bad-deploy (Level-2 harness inside the runner — no Slack)
make scenario NAME=bad-deployment
make eval
```

Expect a FAULT_INJECTED → harnessed resolve path and dual-stage pins. Catalog:
[scenarios.md](scenarios.md).

### Optional — live simulation world

For injectors / Prom / “watch the app break”:

```bash
docker compose --profile evidence --profile simulation up -d
make sim-baseline-gate
make sim-inject ARGS='activate bad_deploy'
# investigate via API/UI; then:
make sim-inject ARGS='reset'
```

Demo app overview: [demo-app.md](demo-app.md). Faults: [sim-faults.md](sim-faults.md).

### Optional — product UI during the talk

```bash
make api-run          # terminal 1
make web-dev          # terminal 2 — http://localhost:3000
# Bearer local-dev (ops) or local-dev-evaluator (eval UI)
```

| View | URL / auth |
| --- | --- |
| Incidents | `/incidents` — `local-dev` |
| Scenario runs | `/eval` — `local-dev-evaluator` |
| Ground truth | `/eval/ground-truth` — evaluator only |

Auth: [auth.md](auth.md). Eval UI: [web.md](web.md).

## Talking points (2–5 min recording — Q4)

1. **Self-hosted** control plane — clone, not multi-tenant SaaS  
2. **Evidence + policy** — AI proposes; remediation only via approval  
3. **Isolation** — GT denied on investigation path (`make test-isolation`)  
4. **Scored demo** — `bad-deployment` → harness approve → `make eval`  
5. **Swap** — leave `simulation` off; wire your AM/Slack
   ([swap-your-app.md](swap-your-app.md), [connect-your-stack.md](connect-your-stack.md))  

## Other scenarios (pointers)

After bad-deploy works:

```bash
make scenario NAME=dependency-timeout && make eval
make scenario NAME=db-exhaustion && make eval
make scenario NAME=memory-leak && make eval
make scenario NAME=cpu-exhaustion && make eval
make scenario NAME=queue-backlog && make eval
make scenario NAME=bad-config && make eval
make scenario NAME=cascading-failure && make eval
```

| NAME | Story beat |
| --- | --- |
| `bad-deployment` | Rollback (hero demo) |
| `dependency-timeout` | Reroute traffic |
| `cascading-failure` | Origin ≠ symptom (SEV1) |

Full table: [scenarios.md](scenarios.md).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Isolation fails | `make compose-core && make migrate`; re-run `make test-isolation` |
| Scored run refuses | Isolation must be green; see [isolation.md](isolation.md) |
| `make scenario` FAILED | Sim/baseline dirty — `make scenario-reset`; check Compose |
| No `.venv` / pytest | `make bootstrap`; use `.venv/bin/pytest` |
| Want live LLM | [byo-llm.md](byo-llm.md) — not required for this demo |

## Cleanup

```bash
make scenario-reset
make compose-down
```

## Related

| Doc | Role |
| --- | --- |
| [quickstart.md](quickstart.md) | Shorter first-incident path |
| [scenarios.md](scenarios.md) | Catalog + CLI |
| [isolation.md](isolation.md) | N8 suite |
| [demo-app.md](demo-app.md) | Bundled simulation |
| Q4 #295 | Record this guide as a short video |
