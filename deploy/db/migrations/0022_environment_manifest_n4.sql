-- N4 / #101: environment_manifest + pin on ScenarioRun (local/test).
-- Cloud digest/Helm/TF fields reserved nullable for O10.

CREATE TABLE scenarios.environment_manifest (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    environment_class text NOT NULL DEFAULT 'local',
    git_sha text,
    git_dirty boolean,
    python_version text,
    platform text,
    compose_project text,
    -- O10 placeholders (nullable; local scores do not require them)
    image_digests jsonb NOT NULL DEFAULT '{}'::jsonb,
    helm_chart_hash text,
    terraform_revision text,
    cloud_env_id text,
    extras jsonb NOT NULL DEFAULT '{}'::jsonb,
    captured_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT environment_manifest_class_check CHECK (
        environment_class IN ('local', 'test', 'staging', 'production-demo')
    )
);

CREATE INDEX environment_manifest_captured_idx
    ON scenarios.environment_manifest (captured_at DESC);

COMMENT ON TABLE scenarios.environment_manifest IS
    'N4: pinned execution identity for reproducible ScenarioRun scores';
COMMENT ON COLUMN scenarios.environment_manifest.image_digests IS
    'O10: image digests for cloud scored runs (optional locally)';

ALTER TABLE scenarios.environment_manifest OWNER TO migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE scenarios.environment_manifest TO ip_runner;
GRANT SELECT, INSERT ON TABLE scenarios.environment_manifest TO ip_evaluator;
GRANT SELECT ON TABLE scenarios.environment_manifest TO ip_app;

ALTER TABLE scenarios.scenario_run
    ADD COLUMN IF NOT EXISTS environment_manifest_id uuid
        REFERENCES scenarios.environment_manifest (id) ON DELETE RESTRICT;

CREATE INDEX scenario_run_manifest_idx
    ON scenarios.scenario_run (environment_manifest_id);

COMMENT ON COLUMN scenarios.scenario_run.environment_manifest_id IS
    'N4: pinned environment_manifest at run create (immutable pin)';
