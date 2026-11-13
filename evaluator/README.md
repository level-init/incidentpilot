# evaluator (`incidentpilot_evaluator`)

Deployable: **evaluator** — scores ScenarioRuns against isolated GroundTruth.

**Owns (N2):** `eval.ground_truth` access helpers (`ground_truth.py`) via
`DATABASE_URL_EVALUATOR` / `ip_evaluator`.

**Owns (N5/N6 surface):** re-exports shared metric engine + operational pin
helpers. Implementation lives in `incidentpilot_shared.eval_metrics` and
`incidentpilot_shared.operational_evaluation` so the API eval routes stay
decoupled. See [docs/eval-metrics.md](../docs/eval-metrics.md).

**Owns (N7 surface):** postmortem-stage pin re-exported via shared
`postmortem_evaluation` (CLOSED + link to operational).

**Owns (N18):** outbox consumer for `eval.operational_pin_requested`
(`pin_consumer.py`). Workers enqueue `scenario_run_id` only; this process
reads GT and pins.

```bash
python -m incidentpilot_evaluator pin once
python -m incidentpilot_evaluator pin          # loop
```

**Must not:** be imported by investigation path (`api`, `worker`, remediation).

Docs: [docs/ground-truth.md](../docs/ground-truth.md),
[docs/eval-pin-hook.md](../docs/eval-pin-hook.md).
