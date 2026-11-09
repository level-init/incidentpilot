-- H6 / #52: Runbook pin + FTS retrieval + RUNBOOK_FACT + checkout seed.
-- Executable authority remains allowed_action_types (not body_markdown).
-- pgvector deferred (Compose uses postgres:16-alpine without vector).

-- ---------------------------------------------------------------------------
-- Incident pin (DIAGNOSED authority binding)
-- ---------------------------------------------------------------------------
ALTER TABLE domain.incident
    ADD COLUMN IF NOT EXISTS pinned_runbook_version_id uuid
        REFERENCES domain.runbook_version (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS incident_pinned_runbook_version_id_idx
    ON domain.incident (pinned_runbook_version_id);

-- ---------------------------------------------------------------------------
-- Evidence kind: RUNBOOK_FACT
-- ---------------------------------------------------------------------------
ALTER TABLE domain.evidence DROP CONSTRAINT IF EXISTS evidence_kind_check;
ALTER TABLE domain.evidence
    ADD CONSTRAINT evidence_kind_check CHECK (
        kind IN (
            'METRIC',
            'LOG',
            'TRACE',
            'CHANGE',
            'ACTION_RESULT',
            'HUMAN_OBSERVATION',
            'ALERT_CONTEXT',
            'RUNBOOK_FACT',
            'OTHER'
        )
    );

-- ---------------------------------------------------------------------------
-- FTS on published runbook versions (hybrid = metadata filters + FTS)
-- ---------------------------------------------------------------------------
ALTER TABLE domain.runbook_version
    ADD COLUMN IF NOT EXISTS search_tsv tsvector
        GENERATED ALWAYS AS (
            to_tsvector(
                'english',
                coalesce(body_markdown, '') || ' ' ||
                coalesce(array_to_string(allowed_action_types, ' '), '')
            )
        ) STORED;

CREATE INDEX IF NOT EXISTS runbook_version_search_tsv_idx
    ON domain.runbook_version USING GIN (search_tsv);

CREATE INDEX IF NOT EXISTS runbook_hypothesis_class_idx
    ON domain.runbook (hypothesis_class);

-- ---------------------------------------------------------------------------
-- Seed: checkout high_error_rate with ROLLBACK_DEPLOYMENT allowed
-- ---------------------------------------------------------------------------
INSERT INTO domain.service (key, display_name, environment)
VALUES ('checkout', 'checkout', 'local')
ON CONFLICT (key, environment) DO UPDATE
    SET display_name = EXCLUDED.display_name,
        updated_at = now();

DO $$
DECLARE
    svc_id uuid;
    rb_id uuid;
    rv_id uuid;
BEGIN
    SELECT id INTO svc_id
    FROM domain.service
    WHERE key = 'checkout' AND environment = 'local';

    INSERT INTO domain.runbook (key, title, service_id, hypothesis_class, description)
    VALUES (
        'checkout.high_error_rate',
        'Checkout high error rate',
        svc_id,
        'high_error_rate',
        'Structured allowlist is allowed_action_types — not this description.'
    )
    ON CONFLICT (key) DO UPDATE
        SET title = EXCLUDED.title,
            service_id = EXCLUDED.service_id,
            hypothesis_class = EXCLUDED.hypothesis_class,
            description = EXCLUDED.description,
            updated_at = now()
    RETURNING id INTO rb_id;

    SELECT id INTO rb_id FROM domain.runbook WHERE key = 'checkout.high_error_rate';

    IF NOT EXISTS (
        SELECT 1 FROM domain.runbook_version
        WHERE runbook_id = rb_id AND version = 1
    ) THEN
        INSERT INTO domain.runbook_version (
            runbook_id, version, status, body_markdown, allowed_action_types, proposed_by
        ) VALUES (
            rb_id,
            1,
            'draft',
            $md$
# Checkout high error rate

Human-facing steps. Prose here must NEVER be treated as an action allowlist.
Even if this text says "SCALE" or "RESTART", only `allowed_action_types` authorizes actions.
$md$,
            ARRAY['ROLLBACK_DEPLOYMENT']::text[],
            'system'
        )
        RETURNING id INTO rv_id;

        UPDATE domain.runbook_version
        SET status = 'published'
        WHERE id = rv_id;

        UPDATE domain.runbook
        SET active_version_id = rv_id,
            updated_at = now()
        WHERE id = rb_id;
    ELSE
        SELECT id INTO rv_id
        FROM domain.runbook_version
        WHERE runbook_id = rb_id AND version = 1;

        UPDATE domain.runbook
        SET active_version_id = COALESCE(active_version_id, rv_id),
            updated_at = now()
        WHERE id = rb_id;
    END IF;
END $$;
