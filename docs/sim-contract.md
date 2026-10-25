# Simulation contract — no GT / root-cause cheats (E6)

IncidentPilot must never see GroundTruth or answer keys through the simulation
surface. This contract fails CI when forbidden APIs or fields appear.

## What is scanned

1. **HTTP routes** — path substrings such as `ground_truth`, `actual-root-cause`, `/gt/`, …
2. **OpenAPI** — path keys and schema property names matching answer-key markers
3. **Source AST** under `simulation/` — route string literals, model field names, and
   args that look like cheats (denylist modules themselves are exempt)

Denylist source: `simulation/common/contract.py`.

## Local / CI

```bash
make test-sim-contract
# runs tests/test_sim_contract.py (+ related) and scripts/sim_contract_scan.py
```

GitHub Actions job `sim-contract` (`.github/workflows/ci.yml`) runs the same
target on every PR to `dev` / `main`.

`make sim-contract-scan` remains a thin wrapper around the scanner only.
