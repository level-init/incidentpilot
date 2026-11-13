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

# Scored verticals (Level 2 harness → dual-stage eval)
make scenario NAME=bad-deployment && make eval
make scenario NAME=dependency-timeout && make eval
```

YAML definitions live under `scenarios/definitions/` (loaded by the runner;
GroundTruth stays evaluator-only).

Docs: [docs/scenarios.md](../docs/scenarios.md).
