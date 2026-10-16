# evaluator (`incidentpilot_evaluator`)

Deployable: **evaluator** — scores ScenarioRuns against isolated GroundTruth.

**Owns (later):** metric engine, OperationalEvaluation / PostmortemEvaluation pins.

**Must not:** be imported by investigation path (`api`, `worker`, remediation).
