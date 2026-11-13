-- N18 / #115: evaluator may claim outbox rows for operational pin delivery.
-- Workers enqueue eval.operational_pin_requested (scenario_run_id only).
-- ip_evaluator updates outbox delivery state; still cannot mutate incidents.
-- ip_app needs scenarios USAGE to look up linked scenario_run_id (0019 granted
-- table SELECT but omitted schema USAGE).

GRANT USAGE ON SCHEMA scenarios TO ip_app;
GRANT SELECT ON TABLE scenarios.scenario TO ip_app;
GRANT SELECT ON TABLE scenarios.scenario_run TO ip_app;

GRANT SELECT, UPDATE ON TABLE domain.outbox_message TO ip_evaluator;

COMMENT ON TABLE domain.outbox_message IS
    'Transactional outbox (B6). N18: ip_evaluator UPDATEs for eval.operational_pin_requested delivery only.';
