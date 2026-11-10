-- I7 / #63: Versioned policy definitions (admin API). Past PolicyDecision rows stay immutable.

CREATE TABLE domain.policy_definition (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_key text NOT NULL DEFAULT 'default',
    version integer NOT NULL,
    version_label text NOT NULL,
    body jsonb NOT NULL DEFAULT '{}'::jsonb,
    notes text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT policy_definition_version_positive CHECK (version >= 1),
    CONSTRAINT policy_definition_key_version_uniq UNIQUE (policy_key, version),
    CONSTRAINT policy_definition_key_label_uniq UNIQUE (policy_key, version_label)
);

CREATE INDEX policy_definition_key_idx ON domain.policy_definition (policy_key);

CREATE TABLE domain.policy_active (
    policy_key text PRIMARY KEY,
    version integer NOT NULL,
    activated_at timestamptz NOT NULL DEFAULT now(),
    activated_by text NOT NULL,
    CONSTRAINT policy_active_version_fk
        FOREIGN KEY (policy_key, version)
        REFERENCES domain.policy_definition (policy_key, version)
);

ALTER TABLE domain.policy_definition OWNER TO migrator;
ALTER TABLE domain.policy_active OWNER TO migrator;

GRANT SELECT, INSERT ON TABLE domain.policy_definition TO ip_app;
-- No UPDATE/DELETE for ip_app — versions are append-only.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE domain.policy_active TO ip_app;
GRANT SELECT ON TABLE domain.policy_definition TO ip_runner, ip_evaluator;
GRANT SELECT ON TABLE domain.policy_active TO ip_runner, ip_evaluator;

-- Forbid mutation of published policy_definition rows.
CREATE OR REPLACE FUNCTION domain.policy_definition_forbid_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'policy_definition is immutable: % forbidden', TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

DROP TRIGGER IF EXISTS policy_definition_forbid_update ON domain.policy_definition;
CREATE TRIGGER policy_definition_forbid_update
    BEFORE UPDATE ON domain.policy_definition
    FOR EACH ROW
    EXECUTE FUNCTION domain.policy_definition_forbid_mutation();

DROP TRIGGER IF EXISTS policy_definition_forbid_delete ON domain.policy_definition;
CREATE TRIGGER policy_definition_forbid_delete
    BEFORE DELETE ON domain.policy_definition
    FOR EACH ROW
    EXECUTE FUNCTION domain.policy_definition_forbid_mutation();

-- Seed default v1 matching I2 engine behavior.
INSERT INTO domain.policy_definition (
    policy_key, version, version_label, body, notes, created_by
) VALUES (
    'default',
    1,
    'v1',
    '{
        "engine": "policy_engine.v1",
        "block_action_types": ["OTHER"],
        "level3_autonomous_action_types": ["ROLLBACK_DEPLOYMENT"]
    }'::jsonb,
    'Initial SYSTEM policy (I2 baseline)',
    'system'
);

INSERT INTO domain.policy_active (policy_key, version, activated_by)
VALUES ('default', 1, 'system');
