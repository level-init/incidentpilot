# evaluator (`incidentpilot_evaluator`)

Deployable: **evaluator** — scores ScenarioRuns against isolated GroundTruth.

**Owns (N2):** `eval.ground_truth` access helpers (`ground_truth.py`) via
`DATABASE_URL_EVALUATOR` / `ip_evaluator`.

**Owns (N5):** deterministic metric engine (`metrics/`) — RootCauseMatchSpec,
invented-citation hard-fail; no LLM wording scores. See
[docs/eval-metrics.md](../docs/eval-metrics.md).

**Owns (later):** OperationalEvaluation / PostmortemEvaluation pins (N6/N7).

ScenarioRun evaluate transitions live in shared
`incidentpilot_shared.scenario_lifecycle` (N3) so the eval HTTP API need not
import this package.

**Must not:** be imported by investigation path (`api`, `worker`, remediation).

Docs: [docs/ground-truth.md](../docs/ground-truth.md).
