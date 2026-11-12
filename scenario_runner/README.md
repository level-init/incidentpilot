# scenario_runner (`incidentpilot_scenario_runner`)

Deployable: **scenario-runner** — drives faults, traffic, and scenario lifecycle.

**Owns (N1):** Scenario catalog + `ScenarioRun` rows, baseline gate before
inject, reset that keeps run history.

**Must not:** read or embed GroundTruth answer keys (evaluator-only).

```bash
PYTHONPATH=scenario_runner:simulation \
  python -m incidentpilot_scenario_runner list
PYTHONPATH=scenario_runner:simulation \
  python -m incidentpilot_scenario_runner run bad_deploy
PYTHONPATH=scenario_runner:simulation \
  python -m incidentpilot_scenario_runner reset
```

Docs: [docs/scenarios.md](../docs/scenarios.md).
