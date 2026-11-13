# Scenario runner (N1)

Scenarios define **reality** (faults + baseline). The runner never reads
GroundTruth (`eval.ground_truth`) — evaluator-only; see [ground-truth.md](ground-truth.md).

## Schema (`scenarios`)

| Table | Purpose |
| --- | --- |
| `scenarios.scenario` | Catalog (key, injector_id, autonomy_level) |
| `scenarios.scenario_run` | Per-run record + baseline payload |

### ScenarioRun status (N1 / N3)

| Status | `passed` | `outcome` (API) | Meaning |
| --- | --- | --- | --- |
| `PENDING` | null | `IN_PROGRESS` | Created |
| `BASELINE_PASSED` | null | `IN_PROGRESS` | Health/ready gate green |
| `FAULT_INJECTED` | null | `IN_PROGRESS` | Injector activated after baseline |
| `FAILED` | **null** | `INVALID_RUN` | Invalid env/baseline/infra — **not** a scored miss |
| `EVALUATED` | **true\|false** | `SCORED_PASS` / `SCORED_FAIL` | Env valid; score pinned |

Product rule: unhealthy baseline → `FAILED`, never `EVALUATED` with
`passed=false`. A scored miss is only `EVALUATED` + `passed=false`.

Eval APIs (entitlement required):

```bash
curl -s -H 'Authorization: Bearer local-dev-evaluator' \
  'http://localhost:8000/eval/scenario-runs?status=EVALUATED'
curl -s -X POST -H 'Authorization: Bearer local-dev-evaluator' \
  -H 'Content-Type: application/json' \
  -d '{"passed":false,"summary":{"root_cause_match":0}}' \
  http://localhost:8000/eval/scenario-runs/<run_uuid>/evaluate
```

`POST …/evaluate` refuses `FAILED` runs (HTTP 409).

## Environment manifest pin (N4)

Every new `ScenarioRun` captures a `scenarios.environment_manifest` row and
stores `environment_manifest_id` (immutable pin). Local/test fields include
`git_sha`, `python_version`, `platform`, `compose_project`. Cloud digest /
Helm / Terraform columns exist as nullable placeholders for O10.

```bash
curl -s -H 'Authorization: Bearer local-dev-evaluator' \
  http://localhost:8000/eval/scenario-runs/<run_uuid>
# → environment_manifest: { environment_class, git_sha, python_version, … }
```

Operational score pin at RESOLVED: [operational-evaluation.md](operational-evaluation.md) (N6).

Scored runs (N9+) require a green isolation suite first:

```bash
make test-isolation
```

See [isolation.md](isolation.md) (N8).

## First scored vertical (N9)

YAML definition: `scenarios/definitions/bad_deploy.yaml` (aliases
`bad-deployment` / `bad_deployment`). Level **2** approval via the I6 eval
harness (no Slack / Level 3). Dual-stage pins: Operational @ RESOLVED,
Postmortem @ CLOSED → `ScenarioRun EVALUATED` with manifest pinned.

```bash
make migrate
make test-isolation
make scenario NAME=bad-deployment && make eval
```

`make scenario` records a FAULT_INJECTED run + Level-2 harness path.
`make eval` pins both evaluation stages and asserts family count = 2.
CI keeps `LLM_PROVIDER=fake`; optional local Gemini is documented in
[llm.md](llm.md).

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
make scenario NAME=bad-deployment            # N9 scored vertical
make eval                                    # N9 dual-stage pins
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
