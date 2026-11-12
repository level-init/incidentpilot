# PostmortemEvaluation (N7)

Second-stage immutable score at **CLOSED**, linked to the N6
`OperationalEvaluation` and the same `environment_manifest` family.

## Semantics

| Concept | Meaning |
| --- | --- |
| Requires | `OperationalEvaluation` for the ScenarioRun + incident `CLOSED` + FINAL postmortem |
| Link | `operational_evaluation_id` FK; manifest id must match operational pin |
| One per run | `UNIQUE (scenario_run_id)` — re-pin returns the same id |
| Immutable | `UPDATE`/`DELETE` forbidden |

Metrics (no LLM wording): FINAL required, ≥1 corrective action, no unsupported
claims, no invented evidence citations. See [eval-metrics.md](eval-metrics.md).

## Two EvaluationResults per family

```bash
curl -s -H 'Authorization: Bearer local-dev-evaluator' \
  http://localhost:8000/eval/scenario-runs/<run_uuid>/evaluation-family
# → count=2, operational_evaluation + postmortem_evaluation
```

## API

```bash
curl -s -X POST -H 'Authorization: Bearer local-dev-evaluator' \
  -H 'Content-Type: application/json' \
  -d '{"incident_id":"<uuid>"}' \
  http://localhost:8000/eval/scenario-runs/<run_uuid>/postmortem-evaluation
```
