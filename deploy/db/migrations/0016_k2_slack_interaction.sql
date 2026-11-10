-- K2 / #76: durable Slack interaction ingress (persist before HTTP ack).

CREATE TABLE domain.slack_interaction (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slack_trigger_id text,
    interaction_type text NOT NULL,
    payload jsonb NOT NULL,
    request_timestamp bigint NOT NULL,
    ingress_id text NOT NULL,
    status text NOT NULL DEFAULT 'RECEIVED',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT slack_interaction_status_check CHECK (
        status IN ('RECEIVED', 'MAPPED', 'FAILED')
    )
);

-- Slack trigger_id is unique when present (interaction retries).
CREATE UNIQUE INDEX slack_interaction_trigger_id_uidx
    ON domain.slack_interaction (slack_trigger_id)
    WHERE slack_trigger_id IS NOT NULL;

CREATE INDEX slack_interaction_created_at_idx
    ON domain.slack_interaction (created_at DESC);

COMMENT ON TABLE domain.slack_interaction IS
    'K2: verified Slack interactive payloads; K3 maps RECEIVED → ApprovalDecision';

ALTER TABLE domain.slack_interaction OWNER TO migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE domain.slack_interaction TO ip_app;
GRANT SELECT ON TABLE domain.slack_interaction TO ip_runner, ip_evaluator;
