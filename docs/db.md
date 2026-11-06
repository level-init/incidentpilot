# Database schemas and roles (A5)

PostgreSQL is the system of record. GroundTruth lives in schema `eval` and is
**evaluator-only**. IncidentPilot app and scenario-runner roles must not read it.

## Schemas (one database: `incidentpilot`)

| Schema | Purpose |
| --- | --- |
| `domain` | IncidentPilot SoR (entity tables in Epic B) |
| `scenarios` | Scenario definitions / run metadata (runner) |
| `eval` | GroundTruth + evaluation pins (evaluator) |

Temporal uses separate databases `temporal` / `temporal_visibility` (Compose init).

## Roles

| Role | Login | Privileges |
| --- | --- | --- |
| `migrator` | yes | DDL + DML on `domain` / `scenarios` / `eval` |
| `ip_app` | yes | DML on `domain` only — **no** `eval` |
| `ip_runner` | yes | DML on `scenarios`, SELECT on `domain` — **no** `eval` |
| `ip_evaluator` | yes | DML on `eval` (incl. `ground_truth`), SELECT on scenarios/domain |

Local default passwords (override via env / `ALTER ROLE` — never for cloud as-is):

| Role | Default password |
| --- | --- |
| `migrator` | `incidentpilot_migrator` |
| `ip_app` | `incidentpilot_app` |
| `ip_runner` | `incidentpilot_runner` |
| `ip_evaluator` | `incidentpilot_evaluator` |

## Connection env vars

```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=incidentpilot

# Bootstrap / Compose superuser (migrations apply as this user)
POSTGRES_USER=incidentpilot
POSTGRES_PASSWORD=incidentpilot

# App roles
DATABASE_URL=postgresql://ip_app:incidentpilot_app@localhost:5432/incidentpilot
DATABASE_URL_RUNNER=postgresql://ip_runner:incidentpilot_runner@localhost:5432/incidentpilot
DATABASE_URL_EVALUATOR=postgresql://ip_evaluator:incidentpilot_evaluator@localhost:5432/incidentpilot
DATABASE_URL_MIGRATOR=postgresql://migrator:incidentpilot_migrator@localhost:5432/incidentpilot

IP_APP_PASSWORD=incidentpilot_app
IP_RUNNER_PASSWORD=incidentpilot_runner
IP_EVALUATOR_PASSWORD=incidentpilot_evaluator
MIGRATOR_PASSWORD=incidentpilot_migrator
```

## Commands

```bash
make compose-core          # Postgres must be up
make migrate               # apply deploy/db/migrations/*.sql
make db-verify-isolation   # ip_app/ip_runner denied GT; app cannot DDL; migrator can
```

Migrations are recorded in `public.schema_migrations`.

## Domain tables (Epic B / B1+)

| Table | Notes |
| --- | --- |
| `domain.service` | Deployable/service identity (`key` + `environment`) |
| `domain.incident` | Includes `incident_revision` (optimistic concurrency) |
| `domain.incident_service` | M:N involvement (`affected` / `suspected` / …) |
| `domain.alert` | Unique IncidentPilot `fingerprint` |
| `domain.evidence` | Append-only factual substrate (UPDATE/DELETE forbidden) |
| `domain.evidence_projection` | Redacted LLM view (`READY` / `BLOCKED`) — G2 |
| `domain.evidence_relation` | Evidence graph edges |
| `domain.change` | Deployments / commits / flags / config signals (G8: AC `source_ref` → column `external_ref`) |
| `domain.hypothesis` | Statuses: PROPOSED / LEADING / CONFIRMED / REJECTED / SUPERSEDED |
| `domain.runbook` | Logical runbook identity |
| `domain.runbook_version` | Versioned body + `allowed_action_types`; published = immutable |

| `domain.action` | Remediation proposal; `is_reversible` / `reverse_action_type` |
| `domain.action_version` | Immutable snapshot; policy/approval/attempt bind here |
| `domain.policy_decision` | Unique per `(action_id, action_version)` |
| `domain.approval` | Unique per `(action_id, action_version)` |
| `domain.execution_attempt` | `RESERVED` before MITIGATING allowed |
| `domain.validation_result` | Post-remediation validation outcome |

| `domain.impact_snapshot` | Point-in-time impact estimate |
| `domain.slo_burn` | SLO burn / error-budget observations |
| `domain.timeline_event` | Append-only process chronicle |
| `domain.audit_event` | Append-only privileged ops audit |
| `domain.ai_invocation` | Minimum AI provenance (artifacts URI later) |
| `domain.postmortem` | DRAFT/FINAL; `corrective_actions` JSON array |

## Incident transitions (B5)

`TransitionIncident` lives in `shared/incidentpilot_shared/domain/transitions.py`.
It enforces Freeze-2 legal edges and `expected_revision` optimistic concurrency.
Persist via `apply_transition(conn, ...)`.

Outbox + idempotency: [outbox.md](outbox.md) (B6). Command layer: B7.
