-- B4 / #9: ImpactSnapshot, SLOBurn, Timeline, Audit, AIInvocation, Postmortem.

-- ---------------------------------------------------------------------------
-- impact_snapshot / slo_burn
-- ---------------------------------------------------------------------------
CREATE TABLE domain.impact_snapshot (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id uuid NOT NULL REFERENCES domain.incident (id) ON DELETE CASCADE,
    captured_at timestamptz NOT NULL DEFAULT now(),
    severity text,
    customer_impact_summary text,
    estimated_affected_users integer,
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX impact_snapshot_incident_id_idx ON domain.impact_snapshot (incident_id);
CREATE INDEX impact_snapshot_captured_at_idx ON domain.impact_snapshot (captured_at DESC);

CREATE TABLE domain.slo_burn (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id uuid NOT NULL REFERENCES domain.incident (id) ON DELETE CASCADE,
    service_id uuid REFERENCES domain.service (id) ON DELETE SET NULL,
    slo_key text NOT NULL,
    window_label text NOT NULL,
    burn_rate numeric(12, 6),
    error_budget_remaining numeric(8, 6),
    observed_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX slo_burn_incident_id_idx ON domain.slo_burn (incident_id);
CREATE INDEX slo_burn_observed_at_idx ON domain.slo_burn (observed_at DESC);

-- ---------------------------------------------------------------------------
-- timeline_event / audit_event (append-only process + privileged chronicles)
-- ---------------------------------------------------------------------------
CREATE TABLE domain.timeline_event (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id uuid NOT NULL REFERENCES domain.incident (id) ON DELETE CASCADE,
    event_type text NOT NULL,
    summary text NOT NULL,
    actor text NOT NULL DEFAULT 'system',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX timeline_event_incident_id_idx ON domain.timeline_event (incident_id);
CREATE INDEX timeline_event_occurred_at_idx ON domain.timeline_event (occurred_at DESC);

CREATE TABLE domain.audit_event (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id uuid REFERENCES domain.incident (id) ON DELETE SET NULL,
    action text NOT NULL,
    actor text NOT NULL,
    resource_type text NOT NULL,
    resource_id text,
    outcome text NOT NULL DEFAULT 'success',
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_event_outcome_check CHECK (
        outcome IN ('success', 'denied', 'error')
    )
);

CREATE INDEX audit_event_incident_id_idx ON domain.audit_event (incident_id);
CREATE INDEX audit_event_occurred_at_idx ON domain.audit_event (occurred_at DESC);
CREATE INDEX audit_event_actor_idx ON domain.audit_event (actor);

CREATE OR REPLACE FUNCTION domain.append_only_forbid_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % forbidden', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

CREATE TRIGGER timeline_event_forbid_update
    BEFORE UPDATE ON domain.timeline_event
    FOR EACH ROW
    EXECUTE FUNCTION domain.append_only_forbid_mutation();

CREATE TRIGGER timeline_event_forbid_delete
    BEFORE DELETE ON domain.timeline_event
    FOR EACH ROW
    EXECUTE FUNCTION domain.append_only_forbid_mutation();

CREATE TRIGGER audit_event_forbid_update
    BEFORE UPDATE ON domain.audit_event
    FOR EACH ROW
    EXECUTE FUNCTION domain.append_only_forbid_mutation();

CREATE TRIGGER audit_event_forbid_delete
    BEFORE DELETE ON domain.audit_event
    FOR EACH ROW
    EXECUTE FUNCTION domain.append_only_forbid_mutation();

-- ---------------------------------------------------------------------------
-- ai_invocation (minimum provenance; full S3 artifacts later in L3)
-- ---------------------------------------------------------------------------
CREATE TABLE domain.ai_invocation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id uuid REFERENCES domain.incident (id) ON DELETE SET NULL,
    purpose text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    prompt_hash text,
    response_hash text,
    input_tokens integer,
    output_tokens integer,
    latency_ms integer,
    status text NOT NULL DEFAULT 'succeeded',
    error_summary text,
    artifact_uri text,
    request_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    response_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_invocation_status_check CHECK (
        status IN ('succeeded', 'failed', 'timeout', 'cancelled')
    )
);

CREATE INDEX ai_invocation_incident_id_idx ON domain.ai_invocation (incident_id);
CREATE INDEX ai_invocation_created_at_idx ON domain.ai_invocation (created_at DESC);

-- ---------------------------------------------------------------------------
-- postmortem
-- ---------------------------------------------------------------------------
CREATE TABLE domain.postmortem (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id uuid NOT NULL REFERENCES domain.incident (id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'DRAFT',
    title text NOT NULL,
    body_markdown text NOT NULL DEFAULT '',
    corrective_actions jsonb NOT NULL DEFAULT '[]'::jsonb,
    cited_evidence_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
    author text,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finalized_at timestamptz,
    CONSTRAINT postmortem_incident_uniq UNIQUE (incident_id),
    CONSTRAINT postmortem_status_check CHECK (status IN ('DRAFT', 'FINAL')),
    CONSTRAINT postmortem_corrective_actions_is_array CHECK (
        jsonb_typeof(corrective_actions) = 'array'
    )
);

CREATE INDEX postmortem_status_idx ON domain.postmortem (status);

CREATE OR REPLACE FUNCTION domain.postmortem_final_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'FINAL' THEN
            RAISE EXCEPTION 'postmortem FINAL cannot be deleted'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.status = 'FINAL' THEN
        RAISE EXCEPTION 'postmortem FINAL cannot be updated'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF NEW.status = 'FINAL' AND OLD.status = 'DRAFT' AND NEW.finalized_at IS NULL THEN
        NEW.finalized_at := now();
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER postmortem_final_immutable_update
    BEFORE UPDATE ON domain.postmortem
    FOR EACH ROW
    EXECUTE FUNCTION domain.postmortem_final_immutable();

CREATE TRIGGER postmortem_final_immutable_delete
    BEFORE DELETE ON domain.postmortem
    FOR EACH ROW
    EXECUTE FUNCTION domain.postmortem_final_immutable();

ALTER TABLE domain.impact_snapshot OWNER TO migrator;
ALTER TABLE domain.slo_burn OWNER TO migrator;
ALTER TABLE domain.timeline_event OWNER TO migrator;
ALTER TABLE domain.audit_event OWNER TO migrator;
ALTER TABLE domain.ai_invocation OWNER TO migrator;
ALTER TABLE domain.postmortem OWNER TO migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    domain.impact_snapshot,
    domain.slo_burn,
    domain.timeline_event,
    domain.audit_event,
    domain.ai_invocation,
    domain.postmortem
TO ip_app;

GRANT SELECT ON TABLE
    domain.impact_snapshot,
    domain.slo_burn,
    domain.timeline_event,
    domain.audit_event,
    domain.ai_invocation,
    domain.postmortem
TO ip_runner, ip_evaluator;
