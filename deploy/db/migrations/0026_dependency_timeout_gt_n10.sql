-- N10 / #107: Tighten dependency_timeout GroundTruth for scored scenario.
-- Evaluator-only; ip_app / ip_runner still cannot SELECT.

UPDATE eval.ground_truth
SET
    version = 2,
    title = 'Dependency timeout',
    origin_service_keys = ARRAY['payment'],
    expected_hypothesis_class = 'dependency_timeout',
    expected_action_types = ARRAY['REROUTE_TRAFFIC'],
    expected_severity = 'SEV2',
    match_spec = '{
        "root_cause": {
            "service_keys": ["payment"],
            "symptom_services": ["payment", "gateway"],
            "hypothesis_class": "dependency_timeout"
        },
        "invented_evidence_ids": "hard_fail",
        "autonomy": {"level": 2, "harness": true, "slack": false},
        "action_types": ["REROUTE_TRAFFIC"],
        "severity": "SEV2"
    }'::jsonb,
    answer_payload = '{
        "injector": "dependency_timeout",
        "symptom_services": ["payment", "gateway"],
        "scenario_yaml": "scenarios/definitions/dependency_timeout.yaml",
        "vertical": "n10"
    }'::jsonb,
    notes = 'N10 scored scenario — Level 2 harness REROUTE_TRAFFIC; no Slack / Level 3',
    updated_at = now()
WHERE scenario_key = 'dependency_timeout';

REVOKE ALL ON TABLE eval.ground_truth FROM PUBLIC;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_app;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_runner;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO migrator;
