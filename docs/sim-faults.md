# Simulation fault injectors (E5)

Reproducible faults in the demo world. Injectors change **service behavior**
only. They do **not** plant IncidentPilot Evidence, and they must not emit
GroundTruth / answer-key labels on metrics or alerts.

Symptoms show up as ordinary telemetry: HTTP errors, latency, process memory,
notification queue depth (`sim_notification_queue_depth`).

## Eight injectors

| Id | Target service(s) | Mechanism (observable) |
| --- | --- | --- |
| `bad_deploy` | payment | High 5xx rate |
| `dependency_timeout` | payment | Long sleep (> gateway timeout) |
| `db_exhaustion` | inventory | 503 / no capacity |
| `memory_leak` | checkout | Per-request heap retention |
| `cpu_exhaustion` | checkout | Per-request CPU burn → latency |
| `queue_backlog` | notification | Artificial delay + queue depth |
| `bad_config` | auth | Valid sessions rejected (401) |
| `cascading_failure` | payment + inventory | Origin latency/errors → gateway symptoms |

## Control API (per sim service)

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/v1/injectors` | Available + active for this process |
| `POST` | `/v1/injectors/{id}/activate` | Optional JSON effect overrides |
| `POST` | `/v1/injectors/reset` | Clear faults on this service |

Override bodies may tweak mechanism params (`latency_ms`, `error_rate`, …).
Fields like `root_cause`, `ground_truth`, `answer_key` are **rejected**.

## CLI

```bash
make sim-inject ARGS='list'
make sim-inject ARGS='activate bad_deploy'
make sim-inject ARGS='status'
make sim-inject ARGS='reset'
```

Or: `./scripts/sim_inject.sh activate dependency_timeout`

## Verify (IP offline)

```bash
docker compose --profile simulation up -d
make sim-baseline-gate
make sim-inject ARGS='activate bad_deploy'
# curl payment / gateway — expect errors; Prom error rate rises
curl -sf http://localhost:8103/metrics | grep sim_http_request_errors
make sim-inject ARGS='reset'
```

Baseline gate before injection: [sim-baseline.md](sim-baseline.md).
Contract (no GT routes): `make sim-contract-scan`.
