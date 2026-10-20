# Outbox and idempotency (B6)

IncidentPilot uses a **transactional outbox** instead of Kafka for durable
async intents (Temporal signals, Slack notifications, etc.).

## At-least-once semantics

1. Domain write + `outbox_message` insert happen in the **same Postgres TX**.
2. A dispatcher (Epic D / K later) polls `status = 'pending'`, delivers, then
   marks `published` (or `failed` with retry via `attempts` / `available_at`).
3. Delivery is **at-least-once**. Consumers must dedupe.

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

## Tables

| Table | Role |
| --- | --- |
| `domain.outbox_message` | Pending/published async intents |
| `domain.idempotency_record` | Consumer / ingress dedupe keys |
