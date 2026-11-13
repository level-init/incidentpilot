# Isolation integrity (N8)

Prove GroundTruth never enters the investigation path. **Required before
scored ScenarioRuns** (N9+: `make scenario NAME=bad-deployment && make eval`;
also `dependency-timeout`, `db-exhaustion`, `memory-leak`, `cpu-exhaustion`, …).

## Suite

```bash
make test-isolation
```

Runs:

1. Static scan (`scripts/scan_isolation_integrity.py`) — no GT SQL / answer-key
   markers in api (except eval routes), worker, remediation, scenario_runner,
   adapters, web
2. Pytest: DB role denial, AI tool deny matrix, ops 403 on `/eval/ground-truth`,
   incident APIs do not leak `answer_payload` / `match_spec`, runner has no GT
   event log
3. Sim contract (E6) — no GT cheat routes on simulation services

Local DB probe (Compose):

```bash
make db-verify-isolation
```

## CI

GitHub Actions job `isolation` runs `make test-isolation` against Postgres after
migrations.

## Boundaries

| Path | GT access |
| --- | --- |
| `ip_app` / `ip_runner` / AI tools | **Denied** |
| `ip_evaluator` + eval-entitled APIs | Allowed |
| Ops incident/hypothesis APIs | Must not embed GT answer keys |

See [ground-truth.md](ground-truth.md), [sim-contract.md](sim-contract.md).
