-- A5 / #4: schemas, roles, and GroundTruth isolation baseline.
-- Applied by scripts/db_migrate.sh as the Compose Postgres owner (bootstrap).
-- Domain entity tables land in Epic B; this only creates eval.ground_truth stub
-- so grant denial can be proven.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- Roles (local default passwords; override later with ALTER ROLE / Secrets Manager)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'migrator') THEN
    CREATE ROLE migrator LOGIN PASSWORD 'incidentpilot_migrator';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ip_app') THEN
    CREATE ROLE ip_app LOGIN PASSWORD 'incidentpilot_app';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ip_runner') THEN
    CREATE ROLE ip_runner LOGIN PASSWORD 'incidentpilot_runner';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ip_evaluator') THEN
    CREATE ROLE ip_evaluator LOGIN PASSWORD 'incidentpilot_evaluator';
  END IF;
END
$$;

-- Harden PUBLIC defaults on this database
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE incidentpilot FROM PUBLIC;

GRANT CONNECT ON DATABASE incidentpilot TO migrator, ip_app, ip_runner, ip_evaluator;

-- ---------------------------------------------------------------------------
-- Schemas
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS domain AUTHORIZATION migrator;
CREATE SCHEMA IF NOT EXISTS scenarios AUTHORIZATION migrator;
CREATE SCHEMA IF NOT EXISTS eval AUTHORIZATION migrator;

REVOKE ALL ON SCHEMA domain FROM PUBLIC;
REVOKE ALL ON SCHEMA scenarios FROM PUBLIC;
REVOKE ALL ON SCHEMA eval FROM PUBLIC;

GRANT USAGE, CREATE ON SCHEMA domain TO migrator;
GRANT USAGE, CREATE ON SCHEMA scenarios TO migrator;
GRANT USAGE, CREATE ON SCHEMA eval TO migrator;

-- App: domain DML only (no CREATE → no DDL)
GRANT USAGE ON SCHEMA domain TO ip_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA domain TO ip_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA domain TO ip_app;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA domain
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ip_app;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA domain
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO ip_app;

-- Runner: scenarios (+ optional read of domain for correlation); never eval
GRANT USAGE ON SCHEMA scenarios TO ip_runner;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA scenarios TO ip_runner;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA scenarios TO ip_runner;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA scenarios
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ip_runner;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA scenarios
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO ip_runner;

GRANT USAGE ON SCHEMA domain TO ip_runner;
GRANT SELECT ON ALL TABLES IN SCHEMA domain TO ip_runner;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA domain
  GRANT SELECT ON TABLES TO ip_runner;

-- Evaluator: eval (incl. GroundTruth) + read scenarios/domain for scoring
GRANT USAGE ON SCHEMA eval TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA eval TO ip_evaluator;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA eval TO ip_evaluator;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA eval
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ip_evaluator;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA eval
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO ip_evaluator;

GRANT USAGE ON SCHEMA scenarios TO ip_evaluator;
GRANT SELECT ON ALL TABLES IN SCHEMA scenarios TO ip_evaluator;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA scenarios
  GRANT SELECT ON TABLES TO ip_evaluator;

GRANT USAGE ON SCHEMA domain TO ip_evaluator;
GRANT SELECT ON ALL TABLES IN SCHEMA domain TO ip_evaluator;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA domain
  GRANT SELECT ON TABLES TO ip_evaluator;

-- Explicit denials (defense in depth): app/runner must not touch eval
REVOKE ALL ON SCHEMA eval FROM ip_app;
REVOKE ALL ON SCHEMA eval FROM ip_runner;

ALTER ROLE migrator SET search_path TO domain, scenarios, eval, public;
ALTER ROLE ip_app SET search_path TO domain, public;
ALTER ROLE ip_runner SET search_path TO scenarios, domain, public;
ALTER ROLE ip_evaluator SET search_path TO eval, scenarios, domain, public;

-- ---------------------------------------------------------------------------
-- GroundTruth stub (evaluator-only). Full GT model lands in #99 (N2).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval.ground_truth (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_key text NOT NULL UNIQUE,
    answer_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE eval.ground_truth OWNER TO migrator;

REVOKE ALL ON TABLE eval.ground_truth FROM PUBLIC;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_app;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_runner;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO migrator;
