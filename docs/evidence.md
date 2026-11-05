# Evidence producers (G1)

Evidence is the only factual substrate. Only **registered producers** may write
it via `append_evidence_command` / `POST /incidents/{id}/evidence`.

## Registered producers

| Identity | How |
| --- | --- |
| `prometheus_collector`, `loki_collector`, `tempo_collector`, `change_collector`, `alert_context`, `test_producer` | Exact name |
| `session:<actor_id>` | Human observations (`POST …/observations`) |
| `ai_sandbox` / `ai_*` | **Denied** |

## HTTP produce

```http
POST /incidents/{incident_id}/evidence
Authorization: Bearer producer:prometheus_collector
Content-Type: application/json

{
  "kind": "METRIC",
  "fingerprint": "checkout-error-rate-5m",
  "summary": "error rate elevated",
  "payload": {"value": 0.12}
}
```

- `producer` / `evidence_id` in the body → **400** (spoof rejected)
- First write → **201**; duplicate `(incident_id, fingerprint)` → **200** same id
- Fingerprints are namespaced as `producer:<caller_fp>` when not already prefixed

## Dedup

`UNIQUE (incident_id, fingerprint)` + `ON CONFLICT DO NOTHING` — immutable
`evidence_id`, no UPDATE of factual columns.
