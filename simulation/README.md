# simulation

Demo distributed system used as IncidentPilot’s production-like world (Epic E).

| Directory | Service | Local port |
| --- | --- | --- |
| `gateway/` | API gateway (checkout orchestration) | `8100` |
| `auth/` | Auth / session validate | `8101` |
| `checkout/` | Orders | `8102` |
| `payment/` | Charges | `8103` |
| `inventory/` | Stock + reservations | `8104` |
| `notification/` | Outbound messages | `8105` |

## Local Compose

```bash
make compose-up PROFILE=simulation
make sim-happy-path
make sim-baseline-gate
make sim-traffic DURATION=60 RPS=1
make sim-contract-scan
```

Baseline health/traffic contract for scenario runners: [docs/sim-baseline.md](../docs/sim-baseline.md).

Fault injectors (eight scenario classes): [docs/sim-faults.md](../docs/sim-faults.md).

```bash
make sim-inject ARGS='activate bad_deploy'
make sim-inject ARGS='reset'
```

Happy path:

```bash
curl -s -X POST http://localhost:8100/v1/checkout \
  -H 'content-type: application/json' \
  -d '{"user_id":"user_demo","token":"tok_demo_user","sku":"SKU-WIDGET","quantity":1}'
```

## Observability (E2)

Each service exposes Prometheus metrics at `/metrics` (`sim_http_requests_total`,
`sim_http_request_errors_total`, `sim_http_request_duration_seconds`) and emits
JSON logs with `timestamp`, `level`, `service`, `message`, and `trace_id` /
`span_id` when a span is active. OpenTelemetry FastAPI + httpx instrumentation
propagates W3C `traceparent` across gateway → upstreams (checkout/payment/…).

Compose wires `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4318` so traces land in
Tempo when the `evidence` profile is up:

```bash
docker compose --profile evidence --profile simulation up -d
make sim-happy-path
make obs-smoke
# Grafana http://localhost:3000  →  folder IncidentPilot / Simulation traffic
```

## Isolation

These services **must not** expose GroundTruth or root-cause oracle routes
(`actual-root-cause`, `ground_truth`, etc.) or answer-key fields. Enforced by
`make test-sim-contract` (CI) — see [docs/sim-contract.md](../docs/sim-contract.md).
