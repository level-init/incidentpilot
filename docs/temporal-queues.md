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
(Temporal requires ≥1 handler) and exit 0 on success.

## Evidence collectors (G3)

`incidentpilot-evidence` registers `collect_prometheus_metrics`,
`collect_loki_logs`, and `collect_tempo_traces`. Those activities use
`PROMETHEUS_URL` / `LOKI_URL` / `TEMPO_URL` and write Evidence via
`append_raw_evidence_with_blob`. Keep those env vars **off** the general worker.

## Collect jobs (G6)

`CollectCycleWorkflow` also runs on `incidentpilot-evidence` (issue name:
tq-evidence-collect — same queue; do not add a fourth queue).

1. Client starts `CollectCycleWorkflow` with a `CollectJob`
   (`incident_id`, `environment`, `cycle_id`, optional window/collectors).
2. Activity `validate_collect_job_scope` re-reads Postgres and enforces
   `ToolScope` — **queue ≠ authz**.
3. Activity `run_collect_cycle` collects METRIC/LOG/TRACE.
4. Workflow signals `IncidentWorkflow.evidence_updated` (`EvidenceUpdated`,
   deduped by `cycle_id`). This is **not** an outbox domain event.

`IncidentWorkflowInput.wait_for_evidence_updated` (default `false`) parks the
parent until the first collect cycle completes.

## IncidentWorkflow (D2)

`incidentpilot-general` runs `IncidentWorkflow`:

`DETECTED → TRIAGING → INVESTIGATING`

Activities take `expected_revision` from a fresh Postgres snapshot, then call
`transition_incident_command`. `StaleRevision` is a **non-retryable** Temporal
error; the workflow re-queries and retries with the new revision (D3). The
workflow never inserts Incident rows (no duplicates on crash-resume). Optional
signal `proceed_after_triaging` pauses after TRIAGING for kill/restart tests.

## Durable timers (D5)

After `INVESTIGATING`, `IncidentWorkflow` can arm three Temporal durable timers
(`WorkflowTimerConfig`):

| Timer name | Default | Purpose (handlers stubbed until I5/J7) |
| --- | --- | --- |
| `investigation_deadline` | 4h | Bound investigation window |
| `approval_timeout` | 30m | Approval hanging approvals |
| `validation_window` | 15m | Post-remediation validation wait |

Timers use `workflow.sleep` and survive worker kill/restart; each name fires
**once** per arming. Queries: `timers_armed`, `timer_fire_count(name)`.
