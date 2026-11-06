# Evidence producers (G1)

Evidence is the only factual substrate. Only **registered producers** may write
it via `append_evidence_command` / `POST /incidents/{id}/evidence`.

## Registered producers

| Identity | How |
| --- | --- |
| `prometheus_collector`, `loki_collector`, `tempo_collector`, `change_collector`, `alert_context`, `deterministic_processor`, `test_producer` | Exact name |
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

## Projections (G2)

On insert, C4 redaction runs and stores `domain.evidence_projection`:

| Status | Meaning |
| --- | --- |
| `READY` | Redacted summary/payload safe for LLM / tool broker |
| `BLOCKED` | Redaction failed — broker must refuse; canonical row unchanged |

Read path for AI: `read_evidence_projection_for_llm(conn, incident_id=…, evidence_id=…)`.
Raises `RedactionError` on missing/BLOCKED — never returns canonical `payload`.

## Collectors (G3)

Evidence-worker activities (queue `incidentpilot-evidence`) scrape observability:

| Activity | Producer | Kind | Env |
| --- | --- | --- | --- |
| `collect_prometheus_metrics` | `prometheus_collector` | `METRIC` | `PROMETHEUS_URL` |
| `collect_loki_logs` | `loki_collector` | `LOG` | `LOKI_URL` |
| `collect_tempo_traces` | `tempo_collector` | `TRACE` | `TEMPO_URL` |

Or call `collect_incident_window(...)` from `incidentpilot_worker.collectors`.

**Privilege:** put Prom/Loki/Tempo URLs only on the evidence-worker process — not
the general `incidentpilot-worker`. Windows are capped at 1 hour.

## Collect cycle + EvidenceUpdated (G6)

`CollectCycleWorkflow` on `incidentpilot-evidence` consumes a `CollectJob`:

1. Server-side scope check (`validate_collect_job_scope` + `ToolScope`)
2. Collect selected collectors for the window
3. Signal `IncidentWorkflow.evidence_updated` with `EvidenceUpdated`

Queue membership is privilege isolation only — not authorization.

## ChangeSource + Change persistence (G8)

Read-only `ChangeSource` adapters return `NormalizedChange`. Persist with
`upsert_change_command` (type / service / time / `source_ref`→`external_ref`).
No mutate methods on the port — collectors that emit CHANGE Evidence are G9.

## COLLECTOR_TRIGGER (G7)

The general worker schedules collect **without** Prom/Loki/Tempo credentials:

1. Activity `trigger_collect_cycle` on `incidentpilot-general`
2. Starts `CollectCycleWorkflow` by name on `incidentpilot-evidence`
   (`ensure_collect_cycle_started`)
3. Evidence-worker still owns `PROMETHEUS_URL` / `LOKI_URL` / `TEMPO_URL`

AI tool schema: `collector_trigger` (`metrics`|`logs`|`traces` + query). H3 will
broker it; G7 only provides the Temporal command. Config audit:
`tests/test_collector_trigger.py`.

## Raw blob upload (G5)

Collectors write RAW Evidence via `append_raw_evidence_with_blob`
(`incidentpilot_shared.evidence_raw`) and `incidentpilot_adapters.blob`:

| Object store | `blob_uri` | Provenance |
| --- | --- | --- |
| Upload OK | `s3://…` | `layer=RAW`, `quality=HIGH`, `content_hash`, `blob_status=UPLOADED` |
| Upload fail / MinIO down | `null` | `layer=RAW`, `quality=MEDIUM`, `content_hash`, `external_ref`, `blob_status=UPLOAD_FAILED` |
| Not configured | `null` | same as fail with `blob_status=STORE_UNAVAILABLE` |

**Rule:** RAW `quality=HIGH` is rejected unless `blob_uri` is set — no fake HIGH.
`append_evidence_command` enforces the same guard for all producers.

Env: `S3_ENDPOINT`, `S3_BUCKET_EVIDENCE`, `MINIO_ROOT_USER` /
`MINIO_ROOT_PASSWORD` (or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`).

## Deterministic processors (G4)

Rule-id processors write **DETERMINISTIC_DERIVED** Evidence (never RAW) and
`DERIVED_FROM` edges to parent collector rows:

| Rule id | Input | Module |
| --- | --- | --- |
| `baseline_compare.v1` | METRIC payload | `processors.baseline` |
| `top_errors.v1` | LOG payload | `processors.top_errors` |

Provenance includes `layer=DETERMINISTIC_DERIVED` and `quality_rule_id`.
Persist via `append_derived_evidence_command` / `process_metric_baseline` /
`process_log_top_errors`.
