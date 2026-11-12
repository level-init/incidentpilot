# GroundTruth (N2)

Answer keys for scored scenario runs. **Evaluator-only** — IncidentPilot app,
scenario-runner, and AI tooling must never read these rows.

## Storage

| Object | Role |
| --- | --- |
| Schema `eval` | Evaluator DML; revoked from `ip_app` / `ip_runner` |
| Table `eval.ground_truth` | One row per `scenario_key` (versioned) |

### Columns (structured)

| Column | Purpose |
| --- | --- |
| `scenario_key` | Matches `scenarios.scenario.key` |
| `version` | Answer-key revision (≥ 1) |
| `origin_service_keys` | Fault origin services |
| `expected_hypothesis_class` | Class label for RootCauseMatchSpec (N5) |
| `expected_action_types` | Remediation types expected |
| `expected_severity` | Optional severity target |
| `match_spec` | JSON scoring inputs (`root_cause`, …) |
| `answer_payload` | Flexible bag (injector metadata, etc.) |
| `notes` | Evaluator commentary — never prompt into IP |

## Isolation

```bash
make db-verify-isolation
# ip_app / ip_runner: SELECT + INSERT denied
# ip_evaluator: SELECT structured columns allowed
```

API (eval entitlement required — not ops Admin):

```bash
curl -s -H 'Authorization: Bearer local-dev-evaluator' \
  'http://localhost:8000/eval/ground-truth?scenario_key=bad_deploy'
```

Ops Responder/Admin → **403**. DB role denial is the second line of defense.

## Seeds

Migration `0020` seeds the eight scenario classes. N9 tightens `bad_deploy`
match specs for the first scored vertical. Formulas:
[eval-metrics.md](eval-metrics.md) (N5).

## Related

ScenarioRun lifecycle (`FAILED` vs `EVALUATED`+`passed=false`):
[scenarios.md](scenarios.md) (N3).
