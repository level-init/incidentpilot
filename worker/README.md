# worker (`incidentpilot_worker`)

Deployable: **incidentpilot-worker** — Temporal worker + investigation reasoning.

Also hosts the **evidence-worker** entrypoint (same package, separate task queue).

| Process | Command | Queue |
| --- | --- | --- |
| `incidentpilot-worker` | `python -m incidentpilot_worker` | `incidentpilot-general` |
| `evidence-worker` | `python -m incidentpilot_worker evidence` | `incidentpilot-evidence` |

Smoke: `python -m incidentpilot_worker smoke` (or `make temporal-queue-smoke`).

**Owns (later):** workflow activities, evidence/reasoning orchestration.

**Does not own:** rollback / privileged remediation keys, GroundTruth access.

See [docs/temporal-queues.md](../docs/temporal-queues.md).
