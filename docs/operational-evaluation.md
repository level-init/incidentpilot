# OperationalEvaluation (N6)

Immutable operational score pin when an incident reaches **RESOLVED**.

## Semantics

| Concept | Meaning |
| --- | --- |
| Pin window | Incident state `RESOLVED`; `pinned_incident_revision` captured |
| One per run | `UNIQUE (scenario_run_id)` — re-pin returns the **same id** |
| Immutable | `UPDATE`/`DELETE` forbidden (trigger + no evaluator UPDATE grant) |
| Scoring | N5 `evaluate_operational` vs GT for the run's `scenario_key` |

Later AI / SoR edits cannot rewrite the pin. That is the N6 guarantee.

## API (eval entitlement)

```bash
# Pin (idempotent)
curl -s -X POST -H 'Authorization: Bearer local-dev-evaluator' \
  -H 'Content-Type: application/json' \
  -d '{"incident_id":"<uuid>"}' \
  http://localhost:8000/eval/scenario-runs/<run_uuid>/operational-evaluation

# Read
curl -s -H 'Authorization: Bearer local-dev-evaluator' \
  http://localhost:8000/eval/operational-evaluations/<eval_uuid>
```

Non-`RESOLVED` incidents → **409**. `FAILED` ScenarioRuns → **409**.

## Schema

`eval.operational_evaluation` — see migration `0023`. Linked
`scenarios.scenario_run.incident_id` is set on pin.

N7 adds a postmortem-stage evaluation that links to this operational pin.
