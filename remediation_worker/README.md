# remediation_worker (`incidentpilot_remediation`)

Deployable: **remediation-worker** — privileged execute / reconcile only.

Polls Temporal queue `incidentpilot-remediation` only:

```bash
python -m incidentpilot_remediation          # run
python -m incidentpilot_remediation smoke    # subscribe smoke
```

See [docs/temporal-queues.md](../docs/temporal-queues.md).

**Owns:** RemediationAdapter calls after **VerifyExecutionAttempt** (J1);
attempt verification against SoR params; later reconcile + narrow identity (J11).

```python
from incidentpilot_remediation.execute import verify_and_execute

verified, result = verify_and_execute(conn, adapter, attempt_id=…, parameters=…)
# Bogus params with a real attempt_id → ParamMismatchError
# Skipping verify → UnverifiedExecutionError
```

**Does not own:** investigation reasoning, GroundTruth, user-facing HTTP.
