# remediation_worker (`incidentpilot_remediation`)

Deployable: **remediation-worker** — privileged execute / reconcile only.

Polls Temporal queue `incidentpilot-remediation` only:

```bash
python -m incidentpilot_remediation          # run
python -m incidentpilot_remediation smoke    # subscribe smoke
```

See [docs/temporal-queues.md](../docs/temporal-queues.md).

**Owns (later):** RemediationAdapter calls, attempt verification, narrow identity.

**Does not own:** investigation reasoning, GroundTruth, user-facing HTTP.
