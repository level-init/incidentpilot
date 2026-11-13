-- N13 / #110: Tighten cpu_exhaustion GroundTruth for scored scenario.
-- Evaluator-only; ip_app / ip_runner still cannot SELECT.

UPDATE eval.ground_truth
SET
    version = 2,
    title = 'CPU / resource exhaustion',
    origin_service_keys = ARRAY['checkout'],
    expected_hypothesis_class = 'resource_exhaustion',
    expected_action_types = ARRAY['SCALE_WORKLOAD'],
    expected_severity = 'SEV2',
    match_spec = '{
        "root_cause": {
            "service_keys": ["checkout"],
            "symptom_services": ["checkout", "gateway"],
            "hypothesis_class": "resource_exhaustion"
        },
        "invented_evidence_ids": "hard_fail",
        "autonomy": {"level": 2, "harness": true, "slack": false},
        "action_types": ["SCALE_WORKLOAD"],
        "severity": "SEV2"
    }'::jsonb,
    answer_payload = '{
        "injector": "cpu_exhaustion",
        "symptom_services": ["checkout", "gateway"],
        "scenario_yaml": "scenarios/definitions/cpu_exhaustion.yaml",
        "vertical": "n13"
    }'::jsonb,
    notes = 'N13 scored scenario — Level 2 harness SCALE_WORKLOAD; no Slack / Level 3',
    updated_at = now()
WHERE scenario_key = 'cpu_exhaustion';

REVOKE ALL ON TABLE eval.ground_truth FROM PUBLIC;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_app;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_runner;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO migrator;
