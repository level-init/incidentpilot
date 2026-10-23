# Temporal task queues (D1 / Freeze-9)

Queue topology isolates **privilege classes**. Agents remain capability roles
inside workers — not twelve microservices. Workflow/activity business logic is
out of scope for D1 (see D2+).

## Queues

| Queue name | Constant | Consumer process (Freeze-9) | Privilege class |
| --- | --- | --- | --- |
| `incidentpilot-general` | `TaskQueue.GENERAL` | `incidentpilot-worker` | orchestration (no rollback keys, no GT) |
| `incidentpilot-evidence` | `TaskQueue.EVIDENCE` | `evidence-worker` | collector / deterministic processors |
| `incidentpilot-remediation` | `TaskQueue.REMEDIATION` | `remediation-worker` | privileged execute / reconcile only |

Source of truth: `shared/incidentpilot_shared/temporal_queues.py`.

## Local entrypoints

| Process | Command | Queues |
| --- | --- | --- |
| `incidentpilot-worker` | `python -m incidentpilot_worker` | `incidentpilot-general` |
| `evidence-worker` | `python -m incidentpilot_worker evidence` | `incidentpilot-evidence` |
| `remediation-worker` | `python -m incidentpilot_remediation` | `incidentpilot-remediation` |

Temporal address defaults to `TEMPORAL_ADDRESS` (`localhost:7233` in Compose).

## Smoke

With `make compose-core` (Temporal healthy):

```bash
make temporal-queue-smoke
# or:
python -m incidentpilot_worker smoke
python -m incidentpilot_worker evidence smoke
python -m incidentpilot_remediation smoke
```

Workers subscribe briefly with a placeholder `queue_subscribe_ping` activity
(Temporal requires ≥1 handler) and exit 0 on success. Real workflows land in D2+.
