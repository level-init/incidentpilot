# remediation_worker (`incidentpilot_remediation`)

Deployable: **remediation-worker** — privileged execute / reconcile only.

Polls Temporal queue `incidentpilot-remediation` only:

```bash
python -m incidentpilot_remediation          # run
python -m incidentpilot_remediation smoke    # subscribe smoke
```

See [docs/temporal-queues.md](../docs/temporal-queues.md).

**Owns:** RemediationAdapter calls after **VerifyExecutionAttempt** (J1);
`ROLLBACK_DEPLOYMENT` sim + reconcile (J2); `RESTART_WORKLOAD` /
`SCALE_WORKLOAD` sim (J3); feature-flag disable/restore + config restore (J4);
`PAUSE_CONSUMER` + `REROUTE_TRAFFIC` (J5, PARTIAL includes observed_state);
`RemediationResult` → `ACTION_RESULT` Evidence via Producer (J6);
narrow K8s RBAC for remediation SA (J11 — see `docs/k8s-rbac.md`).

```python
from incidentpilot_remediation.execute import (
    verify_and_execute,
    verify_reconcile_and_execute,
)

verified, result = verify_and_execute(conn, adapter, attempt_id=…, parameters=…)
# Bogus params with a real attempt_id → ParamMismatchError
# Skipping verify → UnverifiedExecutionError

# J2 preferred path for rollback: reconcile before mutate
verified, result = verify_reconcile_and_execute(conn, adapter, attempt_id=…, parameters=…)
# APPLIED → skip execute (lost-ACK safe)
# UNKNOWN/PARTIAL → BlindRetryForbidden (no blind full retry)
```

**Does not own:** investigation reasoning, GroundTruth, user-facing HTTP.
