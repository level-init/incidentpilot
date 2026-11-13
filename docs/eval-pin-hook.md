# RESOLVED → evaluator pin hook (N18)

Join point between live incident control plane and evaluator scoring.

## Contract

| Actor | May |
| --- | --- |
| Worker / `ip_app` (J8 route, manual resolve) | Lookup linked `scenario_run_id`; enqueue outbox |
| Outbox payload | **`scenario_run_id` only** — no GroundTruth fields |
| Temporal dispatcher | Release `eval.operational_pin_requested` (not a Temporal signal) |
| Evaluator (`ip_evaluator`) | Claim outbox → `pin_operational_evaluation` (reads GT) |

Workers **never** read `eval.ground_truth`. Evaluator **never** mutates incident
state (pin writes eval tables + ScenarioRun score status only).

## Flow

1. Scored / harness path links `scenarios.scenario_run.incident_id` before resolve.
2. Incident reaches **RESOLVED** via J8 (`RECOVERED` validation) or contextual
   manual resolve (M7).
3. Domain command calls `request_operational_evaluation_hook` → outbox event
   `eval.operational_pin_requested`.
4. `python -m incidentpilot_evaluator pin once` (or `pin` loop) delivers the pin.

Ordinary live ops incidents without a linked ScenarioRun → hook no-ops.

```bash
# after RESOLVED with a linked ScenarioRun
python -m incidentpilot_evaluator pin once
# → ok eval pin once: published=N
```

## Authz / isolation

| Check | Expectation |
| --- | --- |
| `ip_app` / worker DSN `SELECT eval.ground_truth` | Denied |
| `ip_app` `SELECT scenarios.scenario_run` (linked id only) | Allowed (schema USAGE + SELECT) |
| Outbox payload keys | Exactly `{scenario_run_id}` |
| Ops Admin without eval entitlement | Cannot call pin API |

See [operational-evaluation.md](operational-evaluation.md), [outbox.md](outbox.md),
[isolation.md](isolation.md).
