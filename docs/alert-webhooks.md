# Alertmanager webhook ingress (F1 / F2)

Separate ingress for Alertmanager. **Not** Slack HMAC — AM uses bearer,
basic, or a shared custom header.

## Endpoint

```http
POST /webhooks/alerts/alertmanager
Content-Type: application/json
```

Success: **202 Accepted** with:

```json
{
  "status": "accepted",
  "ingress_id": "...",
  "idempotent": false,
  "alert_ids": ["..."],
  "fingerprints": ["am:..."],
  "incident_ids": ["..."]
}
```

F2 normalizes each entry in `alerts[]` into `domain.alert` with a stable
IncidentPilot fingerprint (`am:<sha256>`). Vendor AM `fingerprint` is an
input to the hash only. Raw alert JSON is stored in `raw_payload`.

## Correlation (F4)

After upsert, each alert is attached via `correlate_alert_command`:

1. Already linked → keep  
2. Else open incident for same fingerprint  
3. Else open incident with a recent alert on the same `labels.service` (default **30 minutes**)  
4. Else create a new DETECTED incident  

Topology/change data is **not** required. Response includes `incident_ids`.

## Workflow start (F5)

After Postgres commit, the API idempotently starts Temporal
``IncidentWorkflow`` (`id=incident-<uuid>`, queue `incidentpilot-general`).
Already-running workflows are a no-op (`WorkflowAlreadyStartedError`).
The workflow advances **DETECTED → TRIAGING → INVESTIGATING**, then (G10)
kicks off a default collect cycle and waits for ``EvidenceUpdated`` so
citable EV-ids exist for reasoning.

## CloudWatch (F3)

`CloudWatchAdapter` normalizes CW alarm / SNS notification fixtures to the
**same** `NormalizedAlert` shape (`source=cloudwatch`, fingerprint `cw:<sha256>`).
HTTP ingress for CW is optional later — F3 is the adapter + unit fixtures.
See `tests/fixtures/cloudwatch_alarm_*.json` and `tests/test_cloudwatch_normalize.py`.

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

Domain uniqueness is separate: `UNIQUE (fingerprint)` on `domain.alert`. The
same alert delivered under different webhook keys upserts one row.

## Verify

```bash
# no token → 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/webhooks/alerts/alertmanager \
  -H 'content-type: application/json' \
  -d '{"receiver":"x","status":"firing","alerts":[]}'

# with token → 202 (Postgres required)
curl -s -X POST http://localhost:8000/webhooks/alerts/alertmanager \
  -H 'authorization: Bearer dev-am-webhook-token' \
  -H 'content-type: application/json' \
  -H 'idempotency-key: demo-1' \
  -d '{"receiver":"incidentpilot","status":"firing","alerts":[{"status":"firing","labels":{"alertname":"SimHighErrorRate","service":"payment"},"annotations":{"summary":"demo"}}]}'
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
