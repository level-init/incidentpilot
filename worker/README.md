# worker (`incidentpilot_worker`)

Deployable: **incidentpilot-worker** — Temporal worker + investigation reasoning.

Also hosts the **evidence-worker** entrypoint (same package, separate task queue).

| Process | Command | Queue |
| --- | --- | --- |
| `incidentpilot-worker` | `python -m incidentpilot_worker` | `incidentpilot-general` |
| `evidence-worker` | `python -m incidentpilot_worker evidence` | `incidentpilot-evidence` |

Smoke: `python -m incidentpilot_worker smoke` (or `make temporal-queue-smoke`).

**Owns:** `IncidentWorkflow` on `incidentpilot-general` (D2 early path),
transition activities, evidence/reasoning orchestration (later).

**Does not own:** rollback / privileged remediation keys, GroundTruth access.

See [docs/temporal-queues.md](../docs/temporal-queues.md).
