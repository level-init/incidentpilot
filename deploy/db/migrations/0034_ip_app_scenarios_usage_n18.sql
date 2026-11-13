-- N18 follow-up: ensure ip_app can resolve linked ScenarioRun ids.
-- Idempotent if 0033 already applied the same grants.

GRANT USAGE ON SCHEMA scenarios TO ip_app;
GRANT SELECT ON TABLE scenarios.scenario TO ip_app;
GRANT SELECT ON TABLE scenarios.scenario_run TO ip_app;
