-- K4 / #78: Slack thread root per incident (coherent lifecycle updates).

CREATE TABLE domain.slack_incident_thread (
    incident_id uuid PRIMARY KEY REFERENCES domain.incident (id) ON DELETE CASCADE,
    channel text NOT NULL,
    thread_ts text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX slack_incident_thread_channel_idx
    ON domain.slack_incident_thread (channel);

COMMENT ON TABLE domain.slack_incident_thread IS
    'K4: root chat.ts for incident Slack thread; replies share thread_ts';

ALTER TABLE domain.slack_incident_thread OWNER TO migrator;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE domain.slack_incident_thread TO ip_app;
GRANT SELECT ON TABLE domain.slack_incident_thread TO ip_runner, ip_evaluator;
