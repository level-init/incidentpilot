# Validation window + ValidationResult (J7)

After remediation execute writes `ACTION_RESULT` Evidence (J6), the incident
enters `VALIDATING`. A durable Temporal timer `validation_window` (default
**15 minutes**) observes Evidence, then SYSTEM records exactly one
`ValidationResult` per `execution_attempt`.

LLM may explain the result; it **never** chooses the outcome.

## Timer

| Name | Default | Behavior |
| --- | --- | --- |
| `validation_window` | 15m | Durable sleep on `IncidentWorkflow`; survives worker kill |

Arm with `IncidentWorkflowInput.wait_for_validation=True` and
`execution_attempt_id`. Activity `handle_validation_window` runs after the
timer fires.

## Checkout recovery criteria (`checkout_recovery.v1`)

| Threshold | Value | Source |
| --- | --- | --- |
| Max error rate | **0.05** | `docs/sim-baseline.md` |
| Max baseline ratio | **2.0** | `baseline_compare.v1` (G4) |
| Require `ACTION_RESULT` | yes | J6 |
| Require METRIC (or baseline payload) | yes | else `UNKNOWN` |

### Outcomes

| Outcome | Meaning | Incident transition |
| --- | --- | --- |
| `RECOVERED` | error_rate ≤ 0.05 (and no baseline breach) | `VALIDATING → RECOVERED` |
| `STILL_DEGRADED` | error_rate > 0.05 or baseline breached | `VALIDATING → DEGRADED` |
| `UNKNOWN` | missing ACTION_RESULT or METRIC | `VALIDATING → DEGRADED` |
| `FAILED_VALIDATION` | reserved hard-fail | `VALIDATING → DEGRADED` |

Compensation / replan after `DEGRADED` is **J8**.

## One result per attempt

Partial unique index on `domain.validation_result(execution_attempt_id)`.
`record_validation_result_command` is idempotent: a second call returns the
existing row (`inserted=False`).
