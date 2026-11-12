-- M11 / #97: ServiceDependency catalog (Postgres — not Neo4j).
-- Directed edge: from_service depends_on / calls to_service (SYNC_RPC).

CREATE TABLE domain.service_dependency (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    from_service_id uuid NOT NULL REFERENCES domain.service (id) ON DELETE CASCADE,
    to_service_id uuid NOT NULL REFERENCES domain.service (id) ON DELETE CASCADE,
    dependency_type text NOT NULL DEFAULT 'SYNC_RPC',
    discovery_source text NOT NULL DEFAULT 'seed',
    confidence_tier text NOT NULL DEFAULT 'HIGH',
    environment text NOT NULL DEFAULT 'local',
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT service_dependency_no_self CHECK (from_service_id <> to_service_id),
    CONSTRAINT service_dependency_type_check CHECK (
        dependency_type IN (
            'SYNC_RPC',
            'ASYNC_QUEUE',
            'DATA_STORE',
            'CONFIG',
            'OTHER'
        )
    ),
    CONSTRAINT service_dependency_confidence_check CHECK (
        confidence_tier IN ('HIGH', 'MEDIUM', 'LOW')
    ),
    CONSTRAINT service_dependency_edge_uniq UNIQUE (
        from_service_id, to_service_id, dependency_type, environment
    )
);

CREATE INDEX service_dependency_from_idx ON domain.service_dependency (from_service_id);
CREATE INDEX service_dependency_to_idx ON domain.service_dependency (to_service_id);
CREATE INDEX service_dependency_env_idx ON domain.service_dependency (environment);

COMMENT ON TABLE domain.service_dependency IS
    'M11: catalog edges for blast-radius map; from_service calls/depends_on to_service';

ALTER TABLE domain.service_dependency OWNER TO migrator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE domain.service_dependency TO ip_app;
GRANT SELECT ON TABLE domain.service_dependency TO ip_runner, ip_evaluator;

-- Seed sim world services + gateway → upstreams call graph (local).
DO $$
DECLARE
    keys text[] := ARRAY[
        'gateway', 'auth', 'checkout', 'payment', 'inventory', 'notification'
    ];
    k text;
    gateway_id uuid;
    auth_id uuid;
    checkout_id uuid;
    payment_id uuid;
    inventory_id uuid;
    notification_id uuid;
BEGIN
    FOREACH k IN ARRAY keys LOOP
        INSERT INTO domain.service (key, display_name, environment, criticality)
        VALUES (
            k,
            initcap(k),
            'local',
            CASE WHEN k IN ('gateway', 'checkout', 'payment') THEN 'HIGH' ELSE 'MEDIUM' END
        )
        ON CONFLICT (key, environment) DO UPDATE
            SET display_name = EXCLUDED.display_name,
                updated_at = now();
    END LOOP;

    SELECT id INTO gateway_id FROM domain.service WHERE key = 'gateway' AND environment = 'local';
    SELECT id INTO auth_id FROM domain.service WHERE key = 'auth' AND environment = 'local';
    SELECT id INTO checkout_id FROM domain.service WHERE key = 'checkout' AND environment = 'local';
    SELECT id INTO payment_id FROM domain.service WHERE key = 'payment' AND environment = 'local';
    SELECT id INTO inventory_id FROM domain.service WHERE key = 'inventory' AND environment = 'local';
    SELECT id INTO notification_id FROM domain.service WHERE key = 'notification' AND environment = 'local';

    -- Gateway orchestration: auth → inventory → payment → checkout → notification
    INSERT INTO domain.service_dependency (
        from_service_id, to_service_id, dependency_type, discovery_source, confidence_tier
    )
    VALUES
        (gateway_id, auth_id, 'SYNC_RPC', 'sim_seed', 'HIGH'),
        (gateway_id, inventory_id, 'SYNC_RPC', 'sim_seed', 'HIGH'),
        (gateway_id, payment_id, 'SYNC_RPC', 'sim_seed', 'HIGH'),
        (gateway_id, checkout_id, 'SYNC_RPC', 'sim_seed', 'HIGH'),
        (gateway_id, notification_id, 'SYNC_RPC', 'sim_seed', 'HIGH')
    ON CONFLICT (from_service_id, to_service_id, dependency_type, environment) DO NOTHING;
END $$;
