-- B3 / #8: Action + action_version, PolicyDecision, Approval, execution_attempt, ValidationResult.
-- Remediation path: Action → PolicyDecision → Approval? → execution_attempt → adapter.

-- ---------------------------------------------------------------------------
-- action (logical remediation proposal for an incident)
-- ---------------------------------------------------------------------------
CREATE TABLE domain.action (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id uuid NOT NULL REFERENCES domain.incident (id) ON DELETE CASCADE,
    action_type text NOT NULL,
    current_version integer NOT NULL DEFAULT 1,
    target_service_id uuid REFERENCES domain.service (id) ON DELETE SET NULL,
    hypothesis_id uuid REFERENCES domain.hypothesis (id) ON DELETE SET NULL,
    runbook_version_id uuid REFERENCES domain.runbook_version (id) ON DELETE SET NULL,
    -- Reversibility metadata (copied onto each action_version snapshot too)
    is_reversible boolean NOT NULL DEFAULT false,
    reverse_action_type text,
    status text NOT NULL DEFAULT 'PROPOSED',
    proposed_by text NOT NULL,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT action_current_version_positive CHECK (current_version >= 1),
    CONSTRAINT action_type_check CHECK (
        action_type IN (
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
    ),
    CONSTRAINT action_status_check CHECK (
        status IN (
            'PROPOSED',
            'POLICY_EVALUATED',
            'AWAITING_APPROVAL',
            'APPROVED',
            'BLOCKED',
            'EXECUTING',
            'SUCCEEDED',
            'FAILED',
            'CANCELLED'
        )
    ),
    CONSTRAINT action_reverse_requires_flag CHECK (
        reverse_action_type IS NULL OR is_reversible = true
    )
);

CREATE INDEX action_incident_id_idx ON domain.action (incident_id);
CREATE INDEX action_status_idx ON domain.action (status);

-- Immutable versioned snapshot bound by policy / approval / attempt
CREATE TABLE domain.action_version (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_id uuid NOT NULL REFERENCES domain.action (id) ON DELETE CASCADE,
    version integer NOT NULL,
    action_type text NOT NULL,
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    target_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_reversible boolean NOT NULL DEFAULT false,
    reverse_action_type text,
    reverse_parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    proposed_by text NOT NULL,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT action_version_uniq UNIQUE (action_id, version),
    CONSTRAINT action_version_positive CHECK (version >= 1),
    CONSTRAINT action_version_reverse_requires_flag CHECK (
        reverse_action_type IS NULL OR is_reversible = true
    )
);

CREATE INDEX action_version_action_id_idx ON domain.action_version (action_id);

CREATE OR REPLACE FUNCTION domain.action_version_forbid_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'action_version is immutable: % forbidden', TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

CREATE TRIGGER action_version_forbid_update
    BEFORE UPDATE ON domain.action_version
    FOR EACH ROW
    EXECUTE FUNCTION domain.action_version_forbid_mutation();

CREATE TRIGGER action_version_forbid_delete
    BEFORE DELETE ON domain.action_version
    FOR EACH ROW
    EXECUTE FUNCTION domain.action_version_forbid_mutation();

-- ---------------------------------------------------------------------------
-- policy_decision (one per action version)
-- ---------------------------------------------------------------------------
CREATE TABLE domain.policy_decision (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_id uuid NOT NULL,
    action_version integer NOT NULL,
    decision text NOT NULL,
    reason text,
    policy_key text,
    policy_version text,
    decided_at timestamptz NOT NULL DEFAULT now(),
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT policy_decision_action_version_uniq UNIQUE (action_id, action_version),
    CONSTRAINT policy_decision_decision_check CHECK (
        decision IN ('ALLOW_AUTONOMOUS', 'REQUIRE_APPROVAL', 'BLOCK')
    ),
    CONSTRAINT policy_decision_action_version_fk
        FOREIGN KEY (action_id, action_version)
        REFERENCES domain.action_version (action_id, version)
);

CREATE INDEX policy_decision_action_id_idx ON domain.policy_decision (action_id);

-- ---------------------------------------------------------------------------
-- approval (bound to action version; single row per version)
-- ---------------------------------------------------------------------------
CREATE TABLE domain.approval (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_id uuid NOT NULL,
    action_version integer NOT NULL,
    status text NOT NULL DEFAULT 'PENDING',
    decided_by text,
    decided_at timestamptz,
    consumed_at timestamptz,
    expires_at timestamptz,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT approval_action_version_uniq UNIQUE (action_id, action_version),
    CONSTRAINT approval_status_check CHECK (
        status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'CONSUMED')
    ),
    CONSTRAINT approval_action_version_fk
        FOREIGN KEY (action_id, action_version)
        REFERENCES domain.action_version (action_id, version)
);

CREATE INDEX approval_status_idx ON domain.approval (status);

-- ---------------------------------------------------------------------------
-- execution_attempt (operational record; reservable before MITIGATING)
-- ---------------------------------------------------------------------------
CREATE TABLE domain.execution_attempt (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_id uuid NOT NULL,
    action_version integer NOT NULL,
    attempt_number integer NOT NULL DEFAULT 1,
    state text NOT NULL DEFAULT 'RESERVED',
    reserved_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    adapter_result jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_summary text,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT execution_attempt_uniq UNIQUE (action_id, action_version, attempt_number),
    CONSTRAINT execution_attempt_number_positive CHECK (attempt_number >= 1),
    CONSTRAINT execution_attempt_state_check CHECK (
        state IN (
            'RESERVED',
            'RUNNING',
            'SUCCEEDED',
            'FAILED',
            'UNKNOWN',
            'CANCELLED'
        )
    ),
    CONSTRAINT execution_attempt_action_version_fk
        FOREIGN KEY (action_id, action_version)
        REFERENCES domain.action_version (action_id, version)
);

CREATE INDEX execution_attempt_action_id_idx ON domain.execution_attempt (action_id);
CREATE INDEX execution_attempt_state_idx ON domain.execution_attempt (state);

-- ---------------------------------------------------------------------------
-- validation_result (post-remediation validation window outcome)
-- ---------------------------------------------------------------------------
CREATE TABLE domain.validation_result (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id uuid NOT NULL REFERENCES domain.incident (id) ON DELETE CASCADE,
    execution_attempt_id uuid REFERENCES domain.execution_attempt (id) ON DELETE SET NULL,
    action_id uuid,
    action_version integer,
    outcome text NOT NULL,
    criteria jsonb NOT NULL DEFAULT '{}'::jsonb,
    observations jsonb NOT NULL DEFAULT '{}'::jsonb,
    decided_at timestamptz NOT NULL DEFAULT now(),
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT validation_result_outcome_check CHECK (
        outcome IN (
            'RECOVERED',
            'STILL_DEGRADED',
            'UNKNOWN',
            'FAILED_VALIDATION'
        )
    ),
    CONSTRAINT validation_result_action_version_fk
        FOREIGN KEY (action_id, action_version)
        REFERENCES domain.action_version (action_id, version)
);

CREATE INDEX validation_result_incident_id_idx ON domain.validation_result (incident_id);

ALTER TABLE domain.action OWNER TO migrator;
ALTER TABLE domain.action_version OWNER TO migrator;
ALTER TABLE domain.policy_decision OWNER TO migrator;
ALTER TABLE domain.approval OWNER TO migrator;
ALTER TABLE domain.execution_attempt OWNER TO migrator;
ALTER TABLE domain.validation_result OWNER TO migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    domain.action,
    domain.action_version,
    domain.policy_decision,
    domain.approval,
    domain.execution_attempt,
    domain.validation_result
TO ip_app;

GRANT SELECT ON TABLE
    domain.action,
    domain.action_version,
    domain.policy_decision,
    domain.approval,
    domain.execution_attempt,
    domain.validation_result
TO ip_runner, ip_evaluator;
