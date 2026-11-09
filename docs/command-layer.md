# Shared domain command layer (B7)

API and workers share one mutation surface so revision checks, legal
transitions, and outbox rules cannot be bypassed.

## Import path

| Deployable | Module |
| --- | --- |
| Shared implementation | `incidentpilot_shared.domain.commands` |
| API | `incidentpilot_api.commands` (re-export) |
| Worker | `incidentpilot_worker.commands` (re-export) |

## Commands

| Command | Purpose |
| --- | --- |
| `transition_incident_command` | State machine + revision + timeline + outbox |
| `append_evidence_command` | Producer-gated Evidence insert; fingerprint dedup (G1); rejects fake HIGH RAW without `blob_uri` (G5) |
| `append_raw_evidence_with_blob` | Collector helper: S3/MinIO upload then append with honest RAW provenance (G5) |
| `append_derived_evidence_command` | DETERMINISTIC_DERIVED + DERIVED_FROM parents (G4) |
| `link_evidence_relation_command` | Evidence graph edges |
| `decide_approval_command` | PENDING → APPROVED/REJECTED |
| `reserve_execution_attempt_command` | Reserve attempt before MITIGATING |
| `upsert_alert_command` | Insert/update `domain.alert` by fingerprint (F2) |
| `upsert_change_command` | Idempotent `domain.change` by `(source, fingerprint)` (G8); `source_ref`→`external_ref` |
| `create_incident_command` | Create DETECTED incident (+ optional service link) |
| `attach_alert_command` | Set `alert.incident_id` |
| `correlate_alert_command` | Fingerprint/time/service match or create (F4) |
| `propose_hypothesis_command` | SYSTEM insert PROPOSED hypothesis; resolve EV citations (H4) |
| `rank_hypotheses_command` | Heuristic rank/score for PROPOSED rows (not LEADING/CONFIRM) |
| `resolve_incident_evidence_refs` | Map `EV-…` / uuid cites → evidence UUIDs on an incident |
| `diagnose_incident_command` | SYSTEM gate: mark LEADING + `INVESTIGATING→DIAGNOSED` (H5); AI denied |
| `create_runbook_command` / `create_runbook_version_command` | Draft runbook + version (H6) |
| `publish_runbook_version_command` | draft→published (immutable); set active |
| `pin_runbook_version_command` | Pin published version on incident + `RUNBOOK_FACT` |
| `retrieve_runbooks` | Metadata + FTS hybrid search (not a mutator) |

`transition_incident_command(..., DIAGNOSED)` raises `DiagnosedGateError` unless
`via_diagnose_gate=True` (only set by `diagnose_incident_command`).

Pinned runbook authority is `allowed_action_types` — never `body_markdown`.

## Adapter boundary

`incidentpilot_adapters` must not write `domain.*` tables. Adapters are for
outbound I/O; commands own domain mutations.
