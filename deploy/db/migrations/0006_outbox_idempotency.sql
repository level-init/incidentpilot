-- B6 / #11: transactional outbox + idempotency records (no Kafka).

CREATE TABLE domain.outbox_message (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    event_type text NOT NULL,
    payload jsonb NOT NULL,
    headers jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT now(),
    available_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    CONSTRAINT outbox_message_status_check CHECK (
        status IN ('pending', 'published', 'failed')
    ),
    CONSTRAINT outbox_message_attempts_nonneg CHECK (attempts >= 0)
);

CREATE INDEX outbox_message_poll_idx
    ON domain.outbox_message (status, available_at, created_at)
    WHERE status = 'pending';

CREATE INDEX outbox_message_aggregate_idx
    ON domain.outbox_message (aggregate_type, aggregate_id);

CREATE TABLE domain.idempotency_record (
    scope text NOT NULL,
    key text NOT NULL,
    request_hash text,
    response_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    PRIMARY KEY (scope, key)
);

CREATE INDEX idempotency_record_expires_at_idx
    ON domain.idempotency_record (expires_at)
    WHERE expires_at IS NOT NULL;

ALTER TABLE domain.outbox_message OWNER TO migrator;
ALTER TABLE domain.idempotency_record OWNER TO migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    domain.outbox_message,
    domain.idempotency_record
TO ip_app;

GRANT SELECT ON TABLE
    domain.outbox_message,
    domain.idempotency_record
TO ip_runner, ip_evaluator;
