-- N1 / #98: Scenario catalog + ScenarioRun lifecycle (runner schema).
-- Runner never reads eval.ground_truth. EVALUATED scoring lands in N3+.

CREATE TABLE scenarios.scenario (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key text NOT NULL,
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    injector_id text NOT NULL,
    autonomy_level int NOT NULL DEFAULT 2,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT scenario_key_uniq UNIQUE (key),
    CONSTRAINT scenario_autonomy_check CHECK (autonomy_level BETWEEN 1 AND 3)
);

CREATE TABLE scenarios.scenario_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id uuid NOT NULL REFERENCES scenarios.scenario (id) ON DELETE RESTRICT,
    status text NOT NULL DEFAULT 'PENDING',
    failure_kind text,
    failure_detail text,
    baseline_ok boolean,
    baseline_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    injector_id text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    reset_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT scenario_run_status_check CHECK (
        status IN (
            'PENDING',
            'BASELINE_PASSED',
            'FAULT_INJECTED',
            'FAILED'
            -- EVALUATED added in N3 when scoring pins land
        )
    ),
    CONSTRAINT scenario_run_failure_kind_check CHECK (
        failure_kind IS NULL
        OR failure_kind IN (
            'BASELINE',
            'INJECT',
            'INFRA',
            'OTHER'
        )
    )
);

CREATE INDEX scenario_run_scenario_idx ON scenarios.scenario_run (scenario_id);
CREATE INDEX scenario_run_status_idx ON scenarios.scenario_run (status);
CREATE INDEX scenario_run_started_idx ON scenarios.scenario_run (started_at DESC);

COMMENT ON TABLE scenarios.scenario IS
    'N1: scenario definitions (fault class + metadata); no GroundTruth';
COMMENT ON TABLE scenarios.scenario_run IS
    'N1: run records — FAILED = invalid env/baseline; EVALUATED reserved for N3';
COMMENT ON COLUMN scenarios.scenario_run.reset_at IS
    'Set when env faults cleared; row retained (eval history)';

ALTER TABLE scenarios.scenario OWNER TO migrator;
ALTER TABLE scenarios.scenario_run OWNER TO migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE scenarios.scenario TO ip_runner;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE scenarios.scenario_run TO ip_runner;
GRANT SELECT ON TABLE scenarios.scenario TO ip_evaluator;
GRANT SELECT ON TABLE scenarios.scenario_run TO ip_evaluator;
-- App may read run metadata later (eval UI); no write.
GRANT SELECT ON TABLE scenarios.scenario TO ip_app;
GRANT SELECT ON TABLE scenarios.scenario_run TO ip_app;

INSERT INTO scenarios.scenario (key, title, description, injector_id) VALUES
    (
        'bad_deploy',
        'Bad application deployment',
        'Payment returns elevated 5xx after a bad deploy.',
        'bad_deploy'
    ),
    (
        'dependency_timeout',
        'Dependency timeout',
        'Payment sleeps beyond gateway timeout.',
        'dependency_timeout'
    ),
    (
        'db_exhaustion',
        'Database connection exhaustion',
        'Inventory refuses capacity (503).',
        'db_exhaustion'
    ),
    (
        'memory_leak',
        'Memory leak',
        'Checkout retains heap per request.',
        'memory_leak'
    ),
    (
        'cpu_exhaustion',
        'CPU / resource exhaustion',
        'Checkout burns CPU per request.',
        'cpu_exhaustion'
    ),
    (
        'queue_backlog',
        'Queue backlog',
        'Notification queue delay + depth rise.',
        'queue_backlog'
    ),
    (
        'bad_config',
        'Bad configuration / feature flag',
        'Auth rejects valid sessions.',
        'bad_config'
    ),
    (
        'cascading_failure',
        'Cascading failure',
        'Payment + inventory origin; gateway symptoms.',
        'cascading_failure'
    )
ON CONFLICT (key) DO NOTHING;
