# Alertmanager webhook ingress (F1)

Separate ingress for Alertmanager. **Not** Slack HMAC — AM uses bearer,
basic, or a shared custom header.

## Endpoint

```http
POST /webhooks/alerts/alertmanager
Content-Type: application/json
```

Success: **202 Accepted** with `{ "status": "accepted", "ingress_id": "...", "idempotent": false }`.

Normalization into domain `Alert` + fingerprint is **F2**.

## Secret configuration

Set at least one mechanism (env / `.env`):

| Env | Purpose |
| --- | --- |
| `ALERTMANAGER_WEBHOOK_TOKEN` | `Authorization: Bearer <token>` |
| `ALERTMANAGER_BASIC_USER` + `ALERTMANAGER_BASIC_PASSWORD` | HTTP Basic |
| `ALERTMANAGER_HEADER_NAME` (default `X-Alertmanager-Token`) + `ALERTMANAGER_HEADER_VALUE` | Custom header |

If **none** are set, the route returns **503** (misconfigured).  
If secrets are set but the request matches none → **401**.

Local defaults in `.env.example`:

```bash
ALERTMANAGER_WEBHOOK_TOKEN=dev-am-webhook-token
```

## Replay defenses

Idempotency scope: `webhook:alertmanager` (`domain.idempotency_record`).

Key preference:

1. `Idempotency-Key` header  
2. else `X-Request-Id` header  
3. else `body:<sha256>` of canonical JSON  

Duplicates return **200** `{ "status": "duplicate", "idempotent": true }` (success / no-op).

## Verify

```bash
# no token → 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/webhooks/alerts/alertmanager \
  -H 'content-type: application/json' \
  -d '{"receiver":"x","status":"firing","alerts":[]}'

# with token → 202 (Postgres required for idempotency write)
curl -s -X POST http://localhost:8000/webhooks/alerts/alertmanager \
  -H 'authorization: Bearer dev-am-webhook-token' \
  -H 'content-type: application/json' \
  -H 'idempotency-key: demo-1' \
  -d '{"receiver":"incidentpilot","status":"firing","alerts":[]}'
```

Alertmanager receiver example:

```yaml
receivers:
  - name: incidentpilot
    webhook_configs:
      - url: http://incidentpilot-api:8000/webhooks/alerts/alertmanager
        http_config:
          authorization:
            type: Bearer
            credentials: dev-am-webhook-token
```
