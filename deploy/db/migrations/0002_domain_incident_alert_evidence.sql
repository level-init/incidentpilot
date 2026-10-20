-- B1 / #6: core factual + incident graph entities.
-- Evidence rows are append-oriented: UPDATE/DELETE of factual rows is forbidden.

-- ---------------------------------------------------------------------------
-- service
-- ---------------------------------------------------------------------------
CREATE TABLE domain.service (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key text NOT NULL,
    display_name text NOT NULL,
    environment text NOT NULL DEFAULT 'local',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT service_key_env_uniq UNIQUE (key, environment)
);

CREATE INDEX service_environment_idx ON domain.service (environment);

-- ---------------------------------------------------------------------------
-- incident
-- ---------------------------------------------------------------------------
CREATE TABLE domain.incident (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    public_id text NOT NULL,
    state text NOT NULL,
    title text NOT NULL,
    severity text,
    incident_revision bigint NOT NULL DEFAULT 1,
    summary text,
    opened_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    closed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT incident_public_id_uniq UNIQUE (public_id),
    CONSTRAINT incident_revision_positive CHECK (incident_revision >= 1),
    CONSTRAINT incident_state_check CHECK (
        state IN (
            'DETECTED',
            'TRIAGING',
            'INVESTIGATING',
            'DIAGNOSED',
            'AWAITING_APPROVAL',
            'MITIGATING',
            'VALIDATING',
            'RECOVERED',
            'RESOLVED',
            'DEGRADED',
            'POSTMORTEM',
            'CLOSED'
        )
    )
);

CREATE INDEX incident_state_idx ON domain.incident (state);
CREATE INDEX incident_opened_at_idx ON domain.incident (opened_at DESC);

-- ---------------------------------------------------------------------------
-- incident_service (M:N)
-- ---------------------------------------------------------------------------
CREATE TABLE domain.incident_service (
    incident_id uuid NOT NULL REFERENCES domain.incident (id) ON DELETE CASCADE,
    service_id uuid NOT NULL REFERENCES domain.service (id) ON DELETE RESTRICT,
    involvement text NOT NULL DEFAULT 'affected',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (incident_id, service_id),
    CONSTRAINT incident_service_involvement_check CHECK (
        involvement IN ('affected', 'suspected', 'dependency', 'remediation_target')
    )
);

CREATE INDEX incident_service_service_idx ON domain.incident_service (service_id);

-- ---------------------------------------------------------------------------
-- alert
-- ---------------------------------------------------------------------------
CREATE TABLE domain.alert (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fingerprint text NOT NULL,
    source text NOT NULL,
    status text NOT NULL DEFAULT 'firing',
    incident_id uuid REFERENCES domain.incident (id) ON DELETE SET NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    starts_at timestamptz,
    ends_at timestamptz,
    labels jsonb NOT NULL DEFAULT '{}'::jsonb,
    annotations jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT alert_fingerprint_uniq UNIQUE (fingerprint),
    CONSTRAINT alert_source_check CHECK (
        source IN ('alertmanager', 'cloudwatch', 'manual', 'test')
    ),
    CONSTRAINT alert_status_check CHECK (
        status IN ('firing', 'resolved', 'suppressed')
    )
);

CREATE INDEX alert_incident_id_idx ON domain.alert (incident_id);
CREATE INDEX alert_received_at_idx ON domain.alert (received_at DESC);

-- ---------------------------------------------------------------------------
-- evidence (factual substrate — append-only)
-- ---------------------------------------------------------------------------
CREATE TABLE domain.evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    evidence_key text NOT NULL,
    incident_id uuid NOT NULL REFERENCES domain.incident (id) ON DELETE CASCADE,
    kind text NOT NULL,
    fingerprint text NOT NULL,
    summary text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    blob_uri text,
    service_id uuid REFERENCES domain.service (id) ON DELETE SET NULL,
    observed_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    producer text NOT NULL,
    CONSTRAINT evidence_key_uniq UNIQUE (evidence_key),
    CONSTRAINT evidence_incident_fingerprint_uniq UNIQUE (incident_id, fingerprint),
    CONSTRAINT evidence_kind_check CHECK (
        kind IN (
            'METRIC',
            'LOG',
            'TRACE',
            'CHANGE',
            'ACTION_RESULT',
            'HUMAN_OBSERVATION',
            'ALERT_CONTEXT',
            'OTHER'
        )
    )
);

CREATE INDEX evidence_incident_id_idx ON domain.evidence (incident_id);
CREATE INDEX evidence_kind_idx ON domain.evidence (kind);
CREATE INDEX evidence_observed_at_idx ON domain.evidence (observed_at DESC);

CREATE TABLE domain.evidence_relation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    from_evidence_id uuid NOT NULL REFERENCES domain.evidence (id) ON DELETE CASCADE,
    to_evidence_id uuid NOT NULL REFERENCES domain.evidence (id) ON DELETE CASCADE,
    relation_type text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT evidence_relation_uniq UNIQUE (from_evidence_id, to_evidence_id, relation_type),
    CONSTRAINT evidence_relation_no_self CHECK (from_evidence_id <> to_evidence_id),
    CONSTRAINT evidence_relation_type_check CHECK (
        relation_type IN (
            'SUPPORTS',
            'CONTRADICTS',
            'DERIVED_FROM',
            'SAME_SIGNAL',
            'TEMPORAL_NEAR'
        )
    )
);

CREATE INDEX evidence_relation_to_idx ON domain.evidence_relation (to_evidence_id);

-- ---------------------------------------------------------------------------
-- Evidence immutability: no silent overwrite of factual rows
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION domain.evidence_forbid_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'evidence is append-only: % of factual evidence is forbidden', TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

CREATE TRIGGER evidence_forbid_update
    BEFORE UPDATE ON domain.evidence
    FOR EACH ROW
    EXECUTE FUNCTION domain.evidence_forbid_mutation();

CREATE TRIGGER evidence_forbid_delete
    BEFORE DELETE ON domain.evidence
    FOR EACH ROW
    EXECUTE FUNCTION domain.evidence_forbid_mutation();

ALTER TABLE domain.service OWNER TO migrator;
ALTER TABLE domain.incident OWNER TO migrator;
ALTER TABLE domain.incident_service OWNER TO migrator;
ALTER TABLE domain.alert OWNER TO migrator;
ALTER TABLE domain.evidence OWNER TO migrator;
ALTER TABLE domain.evidence_relation OWNER TO migrator;

-- Migrations run as bootstrap owner; re-assert app grants on new tables.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    domain.service,
    domain.incident,
    domain.incident_service,
    domain.alert,
    domain.evidence,
    domain.evidence_relation
TO ip_app;

GRANT SELECT ON TABLE
    domain.service,
    domain.incident,
    domain.incident_service,
    domain.alert,
    domain.evidence,
    domain.evidence_relation
TO ip_runner, ip_evaluator;
