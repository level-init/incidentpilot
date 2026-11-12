# evaluator (`incidentpilot_evaluator`)

Deployable: **evaluator** — scores ScenarioRuns against isolated GroundTruth.

**Owns (N2):** `eval.ground_truth` access helpers (`ground_truth.py`) via
`DATABASE_URL_EVALUATOR` / `ip_evaluator`.

**Owns (later):** metric engine, OperationalEvaluation / PostmortemEvaluation pins.

ScenarioRun evaluate transitions live in shared
`incidentpilot_shared.scenario_lifecycle` (N3) so the eval HTTP API need not
import this package.

**Must not:** be imported by investigation path (`api`, `worker`, remediation).

Docs: [docs/ground-truth.md](../docs/ground-truth.md).
