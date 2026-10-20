# scenario_runner (`incidentpilot_scenario_runner`)

Deployable: **scenario-runner** — drives faults, traffic, and scenario lifecycle.

**Owns (later):** Scenario YAML loading, fault injection triggers, baseline gates.

**Must not:** read or embed GroundTruth answer keys (evaluator-only).
