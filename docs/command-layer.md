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
| `create_approval_command` | PENDING Approval bound to exact `action_version` (I4); duplicate create no-op |
| `decide_approval_command` | PENDING → APPROVED/REJECTED; duplicate same status no-op; reject → action CANCELLED (I4) |
| `consume_approval_command` | Single-use APPROVED → CONSUMED; wrong version → `STALE_ACTION_VERSION` (I4) |
| `assert_approval_authorizes` | Exact-version APPROVED/CONSUMED gate; vN cannot authorize vM (I4) |
| `expire_pending_approvals_command` | TIMEOUT path: PENDING → EXPIRED; actions CANCELLED (I5; no execute) |
| `reserve_execution_attempt_command` | Reserve attempt before MITIGATING |
| `verify_execution_attempt` | J1: SoR param/binding + policy/approval gate before adapter execute |
| `verify_reconcile_and_execute` | J2 remediation-worker: verify → reconcile → execute only if `NOT_APPLIED` |
| `append_action_result_evidence_command` | J6: RemediationResult → `ACTION_RESULT` Evidence (`ACTION_OBSERVATION`; producer `remediation_worker`) |
| `record_validation_result_command` | J7: one `ValidationResult` per `execution_attempt`; optional `VALIDATING→RECOVERED|DEGRADED` |
| `route_validation_outcome_command` | J8: `RECOVERED→RESOLVED`; NO_IMPROVEMENT→`DIAGNOSED`; REGRESSION→stay `DEGRADED` |
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
| `record_impact_snapshot_command` / `compute_impact_snapshot_command` | Impact snapshot citing METRIC Evidence (H7) |
| `record_slo_burn_command` / `compute_slo_burn_command` | SLO burn observation citing METRIC Evidence (H7) |
| `update_incident_severity_command` | SYSTEM rules: hint + impact/SLO/criticality → `incident.severity` (H8); AI denied |
| `retrieve_historical_assist` | Past incidents/postmortems as non-Evidence suggestions (H9; not a mutator) |
| `confirm_hypothesis_command` | SYSTEM class rules → CONFIRMED + optional CAUSED_BY (H10); RECOVERED alone insufficient |
| `propose_action_command` | ProposeAction + immutable `action_version`; type ∈ pinned allowlist (I1) |
| `propose_compensation_action_command` | J9: new Action linked via `compensates_action_id`; fresh PolicyDecision/Approval required |
| `evaluate_policy_command` | SYSTEM EvaluatePolicy → immutable PolicyDecision; AI denied (I2); resolves autonomy via I3; stamps active policy version (I7) |
| `upsert_autonomy_config_command` | Autonomy Levels 1–3 per service/action/env/severity (I3) |
| `publish_policy_version_command` | Append immutable policy_definition version; optional activate (I7) |
| `activate_policy_version_command` | Point `policy_active` at an existing version (I7) |
| `list_policy_definitions` / `load_active_policy_definition` | Policy version history / active snapshot (I7) |

`transition_incident_command(..., DIAGNOSED)` raises `DiagnosedGateError` unless
`via_diagnose_gate=True` (only set by `diagnose_incident_command`).

Pinned runbook authority is `allowed_action_types` — never `body_markdown`.

## Adapter boundary

`incidentpilot_adapters` must not write `domain.*` tables. Adapters are for
outbound I/O; commands own domain mutations.
