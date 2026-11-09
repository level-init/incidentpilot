-- I3 / #59: Autonomy levels 1–3 per service/action/environment/severity.
-- NULL dimension = wildcard. First scored bad-deploy path uses Level 2.

CREATE TABLE domain.autonomy_config (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    service_key text,
    action_type text,
    environment text,
    severity text,
    autonomy_level integer NOT NULL,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT autonomy_config_level_check CHECK (
        autonomy_level IN (1, 2, 3)
    ),
    CONSTRAINT autonomy_config_action_type_check CHECK (
        action_type IS NULL OR action_type IN (
            'ROLLBACK_DEPLOYMENT',
            'RESTART_WORKLOAD',
            'SCALE_WORKLOAD',
            'DISABLE_FEATURE_FLAG',
            'RESTORE_FEATURE_FLAG',
            'RESTORE_CONFIG',
            'PAUSE_CONSUMER',
            'REROUTE_TRAFFIC',
            'OTHER'
        )
    )
);

-- Treat NULL as wildcard for uniqueness (empty string sentinel).
CREATE UNIQUE INDEX autonomy_config_dims_uniq
    ON domain.autonomy_config (
        COALESCE(service_key, ''),
        COALESCE(action_type, ''),
        COALESCE(environment, ''),
        COALESCE(severity, '')
    );

CREATE INDEX autonomy_config_service_key_idx
    ON domain.autonomy_config (service_key);

ALTER TABLE domain.autonomy_config OWNER TO migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE domain.autonomy_config TO ip_app;
GRANT SELECT ON TABLE domain.autonomy_config TO ip_runner, ip_evaluator;

-- Global default: Level 2 (REQUIRE_APPROVAL) — no silent Level 3 production default.
INSERT INTO domain.autonomy_config (
    service_key, action_type, environment, severity, autonomy_level, notes
) VALUES (
    NULL, NULL, NULL, NULL, 2,
    'Global default Level 2 — human/harness approval required'
);

-- First scored bad-deployment spine: checkout rollback in local → Level 2.
INSERT INTO domain.autonomy_config (
    service_key, action_type, environment, severity, autonomy_level, notes
) VALUES (
    'checkout', 'ROLLBACK_DEPLOYMENT', 'local', NULL, 2,
    'First scored bad-deploy path (F4): Level 2 REQUIRE_APPROVAL'
);
