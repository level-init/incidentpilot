-- N3 / #100: ScenarioRun lifecycle — FAILED vs EVALUATED(+pass=false).

ALTER TABLE scenarios.scenario_run
    ADD COLUMN IF NOT EXISTS passed boolean,
    ADD COLUMN IF NOT EXISTS evaluation_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS evaluated_at timestamptz;

-- Replace status check to include EVALUATED.
ALTER TABLE scenarios.scenario_run
    DROP CONSTRAINT IF EXISTS scenario_run_status_check;
ALTER TABLE scenarios.scenario_run
    ADD CONSTRAINT scenario_run_status_check CHECK (
        status IN (
            'PENDING',
            'BASELINE_PASSED',
            'FAULT_INJECTED',
            'FAILED',
            'EVALUATED'
        )
    );

-- FAILED = invalid env (no score). EVALUATED always has an explicit pass bool.
ALTER TABLE scenarios.scenario_run
    DROP CONSTRAINT IF EXISTS scenario_run_outcome_check;
ALTER TABLE scenarios.scenario_run
    ADD CONSTRAINT scenario_run_outcome_check CHECK (
        (
            status = 'FAILED'
            AND passed IS NULL
        )
        OR (
            status = 'EVALUATED'
            AND passed IS NOT NULL
            AND evaluated_at IS NOT NULL
        )
        OR (
            status NOT IN ('FAILED', 'EVALUATED')
            AND passed IS NULL
        )
    );

COMMENT ON COLUMN scenarios.scenario_run.passed IS
    'N3: set only when status=EVALUATED; false = scored miss (env valid)';
COMMENT ON COLUMN scenarios.scenario_run.evaluation_summary IS
    'N3: score bag placeholder; N5 fills metric details';
COMMENT ON TABLE scenarios.scenario_run IS
    'Scenario runs: FAILED=invalid baseline/infra; EVALUATED+passed=false=IP wrong';

-- Evaluator pins scores (N3/N6); runner still owns create/fail/inject.
GRANT UPDATE ON TABLE scenarios.scenario_run TO ip_evaluator;
