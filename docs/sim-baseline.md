# Simulation baseline contract (E4)

Scenario runs must prove the world is healthy **before** fault injection.
A failed baseline means `ScenarioRun FAILED` (infra/baseline), not a scored
detection miss — see [product-overview.md](product-overview.md).

## Health endpoints

| Endpoint | Who | Contract |
| --- | --- | --- |
| `GET /healthz` | every sim service | HTTP 200, JSON `{ "status": "ok", "service": "<name>", … }` |
| `GET /readyz` | gateway only | HTTP 200 when all upstream `/healthz` report `status=ok`; else 503 |

Inventory may include `stock_total`. If stock is exhausted, `status` becomes
`degraded` (still HTTP 200 on `/healthz`) so the **baseline gate fails** until
stock is restored (restart inventory / new compose).

Forbidden GroundTruth / root-cause cheat routes remain banned — see
`make sim-contract-scan`.

## Baseline traffic profile

Generator: `python -m traffic` (from `simulation/` on `PYTHONPATH`) or
`make sim-traffic`.

Default mix (weighted):

| Kind | Weight | Target |
| --- | --- | --- |
| `healthz` | 0.35 | random service `/healthz` |
| `auth_validate` | 0.20 | auth `POST /v1/sessions/validate` |
| `stock_get` | 0.25 | inventory `GET /v1/stock/{sku}` |
| `checkout` | 0.20 | gateway `POST /v1/checkout` (happy path) |

Defaults: **1 rps**, **60s**, max error rate **5%**. Checkout volume stays well
under demo stock (100 widgets / 50 gadgets) at these settings.

## Gate for scenario runner

The N1 runner (`make scenario-run`) records a `ScenarioRun` and marks it
`FAILED` when this gate is red — see [scenarios.md](scenarios.md).

Before injecting faults:

```bash
make sim-baseline-gate    # all /healthz + gateway /readyz
make sim-traffic DURATION=60 RPS=1
# services must still pass the gate after load
make sim-baseline-gate
```

Pass criteria:

1. Every service `/healthz` → `status=ok`
2. Gateway `/readyz` → `status=ok` with upstream checks all `ok`
3. Baseline traffic finishes with `error_rate ≤ 0.05` and end-of-run health gate green

## Local Compose

```bash
docker compose --profile simulation up -d
make sim-baseline-gate
make sim-traffic DURATION=60
```

Optional continuous generator container (`sim-traffic`, same profile) runs until
stopped (`--duration 0`).
