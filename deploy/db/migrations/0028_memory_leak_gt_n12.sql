-- N12 / #109: Tighten memory_leak GroundTruth for scored scenario.
-- Evaluator-only; ip_app / ip_runner still cannot SELECT.
-- Scored path uses RESTART_WORKLOAD (ROLLBACK remains a valid alternate ops choice).

UPDATE eval.ground_truth
SET
    version = 2,
    title = 'Memory leak',
    origin_service_keys = ARRAY['checkout'],
    expected_hypothesis_class = 'resource_exhaustion',
    expected_action_types = ARRAY['RESTART_WORKLOAD'],
    expected_severity = 'SEV2',
    match_spec = '{
        "root_cause": {
            "service_keys": ["checkout"],
            "symptom_services": ["checkout", "gateway"],
            "hypothesis_class": "resource_exhaustion"
        },
        "invented_evidence_ids": "hard_fail",
        "autonomy": {"level": 2, "harness": true, "slack": false},
        "action_types": ["RESTART_WORKLOAD"],
        "alternate_action_types": ["ROLLBACK_DEPLOYMENT"],
        "severity": "SEV2"
    }'::jsonb,
    answer_payload = '{
        "injector": "memory_leak",
        "symptom_services": ["checkout", "gateway"],
        "scenario_yaml": "scenarios/definitions/memory_leak.yaml",
        "vertical": "n12"
    }'::jsonb,
    notes = 'N12 scored scenario — Level 2 harness RESTART_WORKLOAD; no Slack / Level 3',
    updated_at = now()
WHERE scenario_key = 'memory_leak';

REVOKE ALL ON TABLE eval.ground_truth FROM PUBLIC;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_app;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_runner;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO migrator;
