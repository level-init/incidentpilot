-- G2 / #38: LLM Evidence projections (redacted). Canonical evidence stays raw.

CREATE TABLE domain.evidence_projection (
    evidence_id uuid PRIMARY KEY REFERENCES domain.evidence (id) ON DELETE CASCADE,
    status text NOT NULL,
    summary text,
    payload jsonb,
    redacted_fields jsonb NOT NULL DEFAULT '[]'::jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT evidence_projection_status_check CHECK (
        status IN ('READY', 'BLOCKED')
    ),
    CONSTRAINT evidence_projection_ready_has_body CHECK (
        status <> 'READY'
        OR (summary IS NOT NULL AND payload IS NOT NULL)
    ),
    CONSTRAINT evidence_projection_blocked_has_error CHECK (
        status <> 'BLOCKED' OR error IS NOT NULL
    )
);

CREATE INDEX evidence_projection_status_idx
    ON domain.evidence_projection (status);

ALTER TABLE domain.evidence_projection OWNER TO migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE domain.evidence_projection TO ip_app;

GRANT SELECT ON TABLE domain.evidence_projection TO ip_runner, ip_evaluator;
