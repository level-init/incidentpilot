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
| `domain.evidence_relation` | Evidence graph edges |

Hypothesis / Action / etc. land in later B tickets.
