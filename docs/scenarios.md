# Scenario runner (N1)

Scenarios define **reality** (faults + baseline). The runner never reads
GroundTruth (`eval.ground_truth`) — evaluator-only; see [ground-truth.md](ground-truth.md).

## Schema (`scenarios`)

| Table | Purpose |
| --- | --- |
| `scenarios.scenario` | Catalog (key, injector_id, autonomy_level) |
| `scenarios.scenario_run` | Per-run record + baseline payload |

### ScenarioRun status (N1)

| Status | Meaning |
| --- | --- |
| `PENDING` | Created |
| `BASELINE_PASSED` | Health/ready gate green |
| `FAULT_INJECTED` | Injector activated after baseline |
| `FAILED` | Invalid run (baseline/infra/inject) — **not** a scored miss |

`EVALUATED` arrives in N3 when the metric engine pins scores. Product rule:
unhealthy baseline → `FAILED`, never a false “IncidentPilot was wrong.”

## CLI

Uses `DATABASE_URL_RUNNER` (`ip_runner`).

```bash
make migrate
# simulation profile up for real gates / inject
docker compose --profile simulation up -d

make scenario-list
make scenario-run ARGS='bad_deploy'          # baseline → inject
make scenario-run ARGS='bad_deploy --no-inject'
make scenario-reset                          # clear faults; keep run history
PYTHONPATH=scenario_runner:simulation \
  .venv/bin/python -m incidentpilot_scenario_runner show <run_uuid>
```

Exit code **2** when the run is `FAILED` (e.g. dirty baseline).

## Acceptance checks

1. Point sim at a dirty/unhealthy world (or mock gate) → run is `FAILED` /
   `failure_kind=BASELINE`, not `EVALUATED`.
2. `ip_runner` cannot `SELECT` `eval.ground_truth` (see
   `make db-verify-isolation` + N1 tests).
3. `reset` stamps `reset_at` and clears injectors; **rows remain**.

## Verify dirty env

```bash
# With simulation down or degraded, expect FAILED:
make scenario-run ARGS='bad_deploy --no-inject'; echo $?   # 2
```
