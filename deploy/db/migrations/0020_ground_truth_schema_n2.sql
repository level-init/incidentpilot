-- N2 / #99: Full GroundTruth schema + isolation (evaluator-only).
-- Extends the A5 stub. App / runner / AI path must never read these rows.

ALTER TABLE eval.ground_truth
    ADD COLUMN IF NOT EXISTS version int NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS title text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS origin_service_keys text[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS expected_hypothesis_class text,
    ADD COLUMN IF NOT EXISTS expected_action_types text[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS expected_severity text,
    ADD COLUMN IF NOT EXISTS match_spec jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS notes text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE eval.ground_truth
    DROP CONSTRAINT IF EXISTS ground_truth_version_positive;
ALTER TABLE eval.ground_truth
    ADD CONSTRAINT ground_truth_version_positive CHECK (version >= 1);

COMMENT ON TABLE eval.ground_truth IS
    'N2: evaluator-only answer keys; never readable by ip_app / ip_runner / investigation';
COMMENT ON COLUMN eval.ground_truth.match_spec IS
    'RootCauseMatchSpec and related scoring inputs (N5); not prompts for IP';
COMMENT ON COLUMN eval.ground_truth.answer_payload IS
    'Flexible answer bag; prefer structured columns when present';

-- Re-assert isolation (defense in depth after ALTER).
REVOKE ALL ON SCHEMA eval FROM PUBLIC;
REVOKE ALL ON SCHEMA eval FROM ip_app;
REVOKE ALL ON SCHEMA eval FROM ip_runner;
REVOKE ALL ON TABLE eval.ground_truth FROM PUBLIC;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_app;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_runner;

GRANT USAGE ON SCHEMA eval TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO migrator;

-- Seed answer keys for the eight scenario classes (evaluator store only).
INSERT INTO eval.ground_truth (
    scenario_key,
    title,
    version,
    origin_service_keys,
    expected_hypothesis_class,
    expected_action_types,
    expected_severity,
    match_spec,
    answer_payload,
    notes
) VALUES
    (
        'bad_deploy',
        'Bad application deployment',
        1,
        ARRAY['payment'],
        'bad_deployment',
        ARRAY['ROLLBACK_DEPLOYMENT'],
        'SEV2',
        '{"root_cause":{"service_keys":["payment"],"change_types":["DEPLOYMENT"]},"invented_evidence_ids":"hard_fail"}'::jsonb,
        '{"injector":"bad_deploy","symptom_services":["payment","gateway"]}'::jsonb,
        'N9 first scored vertical'
    ),
    (
        'dependency_timeout',
        'Dependency timeout',
        1,
        ARRAY['payment'],
        'dependency_timeout',
        ARRAY['REROUTE_TRAFFIC'],
        'SEV2',
        '{"root_cause":{"service_keys":["payment"]}}'::jsonb,
        '{"injector":"dependency_timeout"}'::jsonb,
        ''
    ),
    (
        'db_exhaustion',
        'Database connection exhaustion',
        1,
        ARRAY['inventory'],
        'resource_exhaustion',
        ARRAY['SCALE_WORKLOAD'],
        'SEV2',
        '{"root_cause":{"service_keys":["inventory"]}}'::jsonb,
        '{"injector":"db_exhaustion"}'::jsonb,
        ''
    ),
    (
        'memory_leak',
        'Memory leak',
        1,
        ARRAY['checkout'],
        'resource_exhaustion',
        ARRAY['RESTART_WORKLOAD', 'ROLLBACK_DEPLOYMENT'],
        'SEV2',
        '{"root_cause":{"service_keys":["checkout"]}}'::jsonb,
        '{"injector":"memory_leak"}'::jsonb,
        ''
    ),
    (
        'cpu_exhaustion',
        'CPU / resource exhaustion',
        1,
        ARRAY['checkout'],
        'resource_exhaustion',
        ARRAY['SCALE_WORKLOAD'],
        'SEV2',
        '{"root_cause":{"service_keys":["checkout"]}}'::jsonb,
        '{"injector":"cpu_exhaustion"}'::jsonb,
        ''
    ),
    (
        'queue_backlog',
        'Queue backlog',
        1,
        ARRAY['notification'],
        'queue_backlog',
        ARRAY['SCALE_WORKLOAD'],
        'SEV3',
        '{"root_cause":{"service_keys":["notification"]}}'::jsonb,
        '{"injector":"queue_backlog"}'::jsonb,
        ''
    ),
    (
        'bad_config',
        'Bad configuration / feature flag',
        1,
        ARRAY['auth'],
        'bad_config',
        ARRAY['TOGGLE_FEATURE_FLAG', 'RESTORE_CONFIG'],
        'SEV2',
        '{"root_cause":{"service_keys":["auth"],"change_types":["FLAG","CONFIG"]}}'::jsonb,
        '{"injector":"bad_config"}'::jsonb,
        ''
    ),
    (
        'cascading_failure',
        'Cascading failure',
        1,
        ARRAY['payment', 'inventory'],
        'cascading_failure',
        ARRAY['ROLLBACK_DEPLOYMENT', 'REROUTE_TRAFFIC'],
        'SEV1',
        '{"root_cause":{"service_keys":["payment","inventory"],"symptom_services":["gateway"]}}'::jsonb,
        '{"injector":"cascading_failure","origin_ne_symptom":true}'::jsonb,
        'Origin ≠ symptom'
    )
ON CONFLICT (scenario_key) DO UPDATE SET
    title = EXCLUDED.title,
    version = EXCLUDED.version,
    origin_service_keys = EXCLUDED.origin_service_keys,
    expected_hypothesis_class = EXCLUDED.expected_hypothesis_class,
    expected_action_types = EXCLUDED.expected_action_types,
    expected_severity = EXCLUDED.expected_severity,
    match_spec = EXCLUDED.match_spec,
    answer_payload = EXCLUDED.answer_payload,
    notes = EXCLUDED.notes,
    updated_at = now();
