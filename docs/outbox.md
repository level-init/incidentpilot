# Outbox and idempotency (B6)

IncidentPilot uses a **transactional outbox** instead of Kafka for durable
async intents (Temporal signals, Slack notifications, etc.).

## At-least-once semantics

1. Domain write + `outbox_message` insert happen in the **same Postgres TX**.
2. The **outbox dispatcher** (D4) polls `status = 'pending'`, signals Temporal
   workflows, then marks `published` (or schedules retry via `available_at` /
   `attempts` / `last_error`).
3. Delivery is **at-least-once**. Consumers must dedupe (workflow tracks
   `message_id`; never re-apply domain transitions from signals).

## Idempotency

`domain.idempotency_record` stores `(scope, key)`.

```python
from incidentpilot_shared import try_begin_idempotent

if not try_begin_idempotent(conn, scope="webhook:alertmanager", key=fingerprint):
    return  # duplicate → success / no-op
# ... perform work ...
```

## Marked operations (outbox required)

For operations that must emit an async intent, use `UnitOfWork(requires_outbox=True)`.
`commit()` raises `OutboxRequiredError` if no outbox row was enqueued.

```python
from incidentpilot_shared import UnitOfWork

uow = UnitOfWork(conn, requires_outbox=True)
# domain writes...
uow.enqueue_outbox(
    aggregate_type="incident",
    aggregate_id=str(incident_id),
    event_type="incident.transitioned",
    payload={"to": "INVESTIGATING"},
)
uow.commit()
```

## Dispatcher → Temporal signals (D4)

Process placement is flexible (local: `incidentpilot-worker`). Mapping:

| `event_type` | Workflow id | Signal |
| --- | --- | --- |
| `incident.transitioned` | `incident-{aggregate_id}` | `domain_event` |
| `incident.created` | `incident-{aggregate_id}` | `domain_event` |

```bash
python -m incidentpilot_worker dispatch once   # one poll batch
python -m incidentpilot_worker dispatch        # loop
```

Crash mid-flight: row stays `pending` under a visibility lease; a later poll
re-signals. `IncidentWorkflow.domain_event` ignores duplicate `message_id`s and
**does not** call TransitionIncident (no double-transition).

## Tables

| Table | Role |
| --- | --- |
| `domain.outbox_message` | Pending/published async intents |
| `domain.idempotency_record` | Consumer / ingress dedupe keys |
