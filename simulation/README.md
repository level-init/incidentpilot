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
make sim-contract-scan
```

Happy path:

```bash
curl -s -X POST http://localhost:8100/v1/checkout \
  -H 'content-type: application/json' \
  -d '{"user_id":"user_demo","token":"tok_demo_user","sku":"SKU-WIDGET","quantity":1}'
```

## Isolation

These services **must not** expose GroundTruth or root-cause oracle routes
(`actual-root-cause`, `ground_truth`, etc.). Enforced by `make sim-contract-scan`
and `tests/test_sim_services.py`.
