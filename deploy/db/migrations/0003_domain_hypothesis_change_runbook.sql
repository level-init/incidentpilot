-- B2 / #7: Hypothesis, Change, Runbook + immutable published RunbookVersion.

-- ---------------------------------------------------------------------------
-- change (deployment / commit / flag / config signals — factual-ish records)
-- ---------------------------------------------------------------------------
CREATE TABLE domain.change (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    change_key text NOT NULL,
    change_type text NOT NULL,
    service_id uuid REFERENCES domain.service (id) ON DELETE SET NULL,
    summary text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    external_ref text,
    fingerprint text NOT NULL,
    observed_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT change_key_uniq UNIQUE (change_key),
    CONSTRAINT change_source_fingerprint_uniq UNIQUE (source, fingerprint),
    CONSTRAINT change_type_check CHECK (
        change_type IN (
            'DEPLOYMENT',
            'COMMIT',
            'PULL_REQUEST',
            'FEATURE_FLAG',
            'CONFIG',
            'SCALE',
            'ROLLBACK',
            'OTHER'
        )
    )
);

CREATE INDEX change_service_id_idx ON domain.change (service_id);
CREATE INDEX change_observed_at_idx ON domain.change (observed_at DESC);
CREATE INDEX change_type_idx ON domain.change (change_type);

-- ---------------------------------------------------------------------------
-- hypothesis (interpretation — SYSTEM writes; AI may propose via provenance)
-- ---------------------------------------------------------------------------
CREATE TABLE domain.hypothesis (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id uuid NOT NULL REFERENCES domain.incident (id) ON DELETE CASCADE,
    status text NOT NULL,
    statement text NOT NULL,
    rationale text,
    hypothesis_class text,
    confidence numeric(5, 4),
    rank integer,
    proposed_by text NOT NULL,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    cited_evidence_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
    leading_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT hypothesis_status_check CHECK (
        status IN (
            'PROPOSED',
            'LEADING',
            'CONFIRMED',
            'REJECTED',
            'SUPERSEDED'
        )
    ),
    CONSTRAINT hypothesis_confidence_range CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    )
);

CREATE INDEX hypothesis_incident_id_idx ON domain.hypothesis (incident_id);
CREATE INDEX hypothesis_status_idx ON domain.hypothesis (status);
CREATE UNIQUE INDEX hypothesis_one_leading_per_incident_idx
    ON domain.hypothesis (incident_id)
    WHERE status = 'LEADING';

-- ---------------------------------------------------------------------------
-- runbook + runbook_version
-- ---------------------------------------------------------------------------
CREATE TABLE domain.runbook (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key text NOT NULL,
    title text NOT NULL,
    service_id uuid REFERENCES domain.service (id) ON DELETE SET NULL,
    hypothesis_class text,
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT runbook_key_uniq UNIQUE (key)
);

CREATE TABLE domain.runbook_version (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    runbook_id uuid NOT NULL REFERENCES domain.runbook (id) ON DELETE CASCADE,
    version integer NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    body_markdown text NOT NULL,
    allowed_action_types text[] NOT NULL DEFAULT '{}'::text[],
    proposed_by text,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    CONSTRAINT runbook_version_uniq UNIQUE (runbook_id, version),
    CONSTRAINT runbook_version_positive CHECK (version >= 1),
    CONSTRAINT runbook_version_status_check CHECK (
        status IN ('draft', 'published', 'retired')
    )
);

CREATE INDEX runbook_version_runbook_id_idx ON domain.runbook_version (runbook_id);
CREATE INDEX runbook_version_status_idx ON domain.runbook_version (status);

ALTER TABLE domain.runbook
    ADD COLUMN active_version_id uuid REFERENCES domain.runbook_version (id) ON DELETE SET NULL;

-- Published (and retired) versions are immutable — no silent edits.
CREATE OR REPLACE FUNCTION domain.runbook_version_forbid_published_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status IN ('published', 'retired') THEN
            RAISE EXCEPTION
                'runbook_version is immutable once published: DELETE forbidden'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.status IN ('published', 'retired') THEN
        RAISE EXCEPTION
            'runbook_version is immutable once published: UPDATE forbidden'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF NEW.status = 'published' AND OLD.status = 'draft' AND NEW.published_at IS NULL THEN
        NEW.published_at := now();
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER runbook_version_forbid_published_update
    BEFORE UPDATE ON domain.runbook_version
    FOR EACH ROW
    EXECUTE FUNCTION domain.runbook_version_forbid_published_mutation();

CREATE TRIGGER runbook_version_forbid_published_delete
    BEFORE DELETE ON domain.runbook_version
    FOR EACH ROW
    EXECUTE FUNCTION domain.runbook_version_forbid_published_mutation();

ALTER TABLE domain.change OWNER TO migrator;
ALTER TABLE domain.hypothesis OWNER TO migrator;
ALTER TABLE domain.runbook OWNER TO migrator;
ALTER TABLE domain.runbook_version OWNER TO migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    domain.change,
    domain.hypothesis,
    domain.runbook,
    domain.runbook_version
TO ip_app;

GRANT SELECT ON TABLE
    domain.change,
    domain.hypothesis,
    domain.runbook,
    domain.runbook_version
TO ip_runner, ip_evaluator;
