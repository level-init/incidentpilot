# Eval metric engine (N5)

Deterministic operational scoring for ScenarioRuns. **No LLM wording /
prose-similarity metrics.** GroundTruth drives match specs; IncidentPilot SoR
supplies observations.

Package: `incidentpilot_shared.eval_metrics` (re-exported as
`incidentpilot_evaluator.metrics`).

## Inputs

| Object | Source |
| --- | --- |
| `IncidentScoreInput` | Confirmed hypothesis class, citations, services, actions, severity |
| `RootCauseMatchSpec` | `eval.ground_truth.match_spec.root_cause` + structured GT columns |

## Metrics

### `invented_evidence_citations` (always applicable)

```text
invented = cited_evidence_ids \ known_evidence_ids
if |invented| > 0 → hard_fail, score = 0
else → score = 1
```

Invented / hallucinated `EV-…` citations **always fail** the run (not a soft miss).

### `root_cause_match` (applicable when spec non-empty)

Equal-weight mean of applicable parts:

| Part | When | Formula |
| --- | --- | --- |
| `hypothesis_class` | expected class set | `1` if confirmed class equals expected else `0` |
| `service_recall` | expected service keys set | `\|obs ∩ exp\| / \|exp\|` |
| `change_recall` | expected change types set | `\|obs ∩ exp\| / \|exp\|` |

### `action_type_match` (applicable when GT `expected_action_types` non-empty)

```text
score = |expected ∩ executed| / |expected ∪ executed|   # Jaccard
```

### `severity_match` (applicable when GT `expected_severity` set)

```text
score = 1 if observed == expected else 0
```

## Aggregation (`evaluate_operational`)

1. If any metric `hard_fail` → **`passed=false`**, aggregate score `0`.
2. Else weighted mean of applicable scoring metrics (citation gate excluded once passed):

| Metric | Weight |
| --- | --- |
| `root_cause_match` | 0.5 |
| `action_type_match` | 0.3 |
| `severity_match` | 0.2 |

Weights renormalize over applicable metrics only.

3. **`passed = aggregate_score ≥ threshold`** (default **0.7**).

`EVALUATED` + `passed=false` means the environment was valid and IncidentPilot
missed — distinct from `ScenarioRun FAILED` (invalid baseline). See
[scenarios.md](scenarios.md).

## Explicitly excluded

- LLM free-text / wording similarity
- Calibrated probabilities
- Scoring from GroundTruth leaked into prompts (isolation: [ground-truth.md](ground-truth.md))
