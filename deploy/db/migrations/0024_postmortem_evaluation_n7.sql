-- N7 / #104: PostmortemEvaluation pin at CLOSED (links OperationalEvaluation).

CREATE TABLE eval.postmortem_evaluation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_run_id uuid NOT NULL REFERENCES scenarios.scenario_run (id) ON DELETE RESTRICT,
    operational_evaluation_id uuid NOT NULL
        REFERENCES eval.operational_evaluation (id) ON DELETE RESTRICT,
    incident_id uuid NOT NULL REFERENCES domain.incident (id) ON DELETE RESTRICT,
    postmortem_id uuid NOT NULL REFERENCES domain.postmortem (id) ON DELETE RESTRICT,
    pinned_incident_revision bigint NOT NULL,
    environment_manifest_id uuid REFERENCES scenarios.environment_manifest (id) ON DELETE RESTRICT,
    ground_truth_id uuid REFERENCES eval.ground_truth (id) ON DELETE RESTRICT,
    scenario_key text NOT NULL,
    passed boolean NOT NULL,
    score double precision,
    hard_fail boolean NOT NULL DEFAULT false,
    threshold double precision NOT NULL DEFAULT 0.7,
    metrics_payload jsonb NOT NULL DEFAULT '[]'::jsonb,
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    metric_engine_version text NOT NULL DEFAULT 'n7.v1',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT postmortem_evaluation_revision_positive CHECK (pinned_incident_revision >= 1),
    CONSTRAINT postmortem_evaluation_run_uniq UNIQUE (scenario_run_id),
    CONSTRAINT postmortem_evaluation_ops_uniq UNIQUE (operational_evaluation_id)
);

CREATE INDEX postmortem_evaluation_incident_idx
    ON eval.postmortem_evaluation (incident_id);
CREATE INDEX postmortem_evaluation_created_idx
    ON eval.postmortem_evaluation (created_at DESC);

COMMENT ON TABLE eval.postmortem_evaluation IS
    'N7: immutable postmortem-stage pin at CLOSED; same manifest family as operational';

ALTER TABLE eval.postmortem_evaluation OWNER TO migrator;

REVOKE ALL ON TABLE eval.postmortem_evaluation FROM PUBLIC;
REVOKE ALL ON TABLE eval.postmortem_evaluation FROM ip_app;
REVOKE ALL ON TABLE eval.postmortem_evaluation FROM ip_runner;
GRANT SELECT, INSERT ON TABLE eval.postmortem_evaluation TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.postmortem_evaluation TO migrator;

CREATE OR REPLACE FUNCTION eval.deny_postmortem_evaluation_mutate()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'eval.postmortem_evaluation is immutable (N7)';
END;
$$;

DROP TRIGGER IF EXISTS postmortem_evaluation_no_update ON eval.postmortem_evaluation;
CREATE TRIGGER postmortem_evaluation_no_update
    BEFORE UPDATE OR DELETE ON eval.postmortem_evaluation
    FOR EACH ROW
    EXECUTE FUNCTION eval.deny_postmortem_evaluation_mutate();
