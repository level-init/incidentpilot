# evaluator (`incidentpilot_evaluator`)

Deployable: **evaluator** — scores ScenarioRuns against isolated GroundTruth.

**Owns (N2):** `eval.ground_truth` access helpers (`ground_truth.py`) via
`DATABASE_URL_EVALUATOR` / `ip_evaluator`.

**Owns (later):** metric engine, OperationalEvaluation / PostmortemEvaluation pins.

**Must not:** be imported by investigation path (`api`, `worker`, remediation).

Docs: [docs/ground-truth.md](../docs/ground-truth.md).
