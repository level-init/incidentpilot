# evaluator (`incidentpilot_evaluator`)

Deployable: **evaluator** — scores ScenarioRuns against isolated GroundTruth.

**Owns (N2):** `eval.ground_truth` access helpers (`ground_truth.py`) via
`DATABASE_URL_EVALUATOR` / `ip_evaluator`.

**Owns (N5/N6 surface):** re-exports shared metric engine + operational pin
helpers. Implementation lives in `incidentpilot_shared.eval_metrics` and
`incidentpilot_shared.operational_evaluation` so the API eval routes stay
decoupled. See [docs/eval-metrics.md](../docs/eval-metrics.md).

**Owns (later):** PostmortemEvaluation pins (N7).

**Must not:** be imported by investigation path (`api`, `worker`, remediation).

Docs: [docs/ground-truth.md](../docs/ground-truth.md).
