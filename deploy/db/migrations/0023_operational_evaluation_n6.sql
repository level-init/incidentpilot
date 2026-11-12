-- N6 / #103: OperationalEvaluation pin at RESOLVED (immutable, idempotent).

CREATE TABLE eval.operational_evaluation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_run_id uuid NOT NULL REFERENCES scenarios.scenario_run (id) ON DELETE RESTRICT,
    incident_id uuid NOT NULL REFERENCES domain.incident (id) ON DELETE RESTRICT,
    pinned_incident_revision bigint NOT NULL,
    environment_manifest_id uuid REFERENCES scenarios.environment_manifest (id) ON DELETE RESTRICT,
    ground_truth_id uuid REFERENCES eval.ground_truth (id) ON DELETE RESTRICT,
    ground_truth_version int,
    scenario_key text NOT NULL,
    passed boolean NOT NULL,
    score double precision,
    hard_fail boolean NOT NULL DEFAULT false,
    threshold double precision NOT NULL DEFAULT 0.7,
    metrics_payload jsonb NOT NULL DEFAULT '[]'::jsonb,
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    metric_engine_version text NOT NULL DEFAULT 'n5.v1',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT operational_evaluation_revision_positive CHECK (pinned_incident_revision >= 1),
    CONSTRAINT operational_evaluation_run_uniq UNIQUE (scenario_run_id)
);

CREATE INDEX operational_evaluation_incident_idx
    ON eval.operational_evaluation (incident_id);
CREATE INDEX operational_evaluation_created_idx
    ON eval.operational_evaluation (created_at DESC);

COMMENT ON TABLE eval.operational_evaluation IS
    'N6: immutable operational score pin at RESOLVED; one per ScenarioRun';

ALTER TABLE eval.operational_evaluation OWNER TO migrator;

REVOKE ALL ON TABLE eval.operational_evaluation FROM PUBLIC;
REVOKE ALL ON TABLE eval.operational_evaluation FROM ip_app;
REVOKE ALL ON TABLE eval.operational_evaluation FROM ip_runner;
GRANT SELECT, INSERT ON TABLE eval.operational_evaluation TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.operational_evaluation TO migrator;
-- No UPDATE/DELETE for evaluator — immutability also enforced by trigger.

CREATE OR REPLACE FUNCTION eval.deny_operational_evaluation_mutate()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'eval.operational_evaluation is immutable (N6)';
END;
$$;

DROP TRIGGER IF EXISTS operational_evaluation_no_update ON eval.operational_evaluation;
CREATE TRIGGER operational_evaluation_no_update
    BEFORE UPDATE OR DELETE ON eval.operational_evaluation
    FOR EACH ROW
    EXECUTE FUNCTION eval.deny_operational_evaluation_mutate();

ALTER TABLE scenarios.scenario_run
    ADD COLUMN IF NOT EXISTS incident_id uuid REFERENCES domain.incident (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS scenario_run_incident_idx
    ON scenarios.scenario_run (incident_id);

COMMENT ON COLUMN scenarios.scenario_run.incident_id IS
    'Optional link to domain incident for operational eval pin (N6)';
