-- N9 / #106: Tighten bad_deploy GroundTruth match_spec for first scored vertical.
-- Evaluator-only; ip_app / ip_runner still cannot SELECT.

UPDATE eval.ground_truth
SET
    version = 2,
    title = 'Bad application deployment',
    origin_service_keys = ARRAY['payment'],
    expected_hypothesis_class = 'bad_deployment',
    expected_action_types = ARRAY['ROLLBACK_DEPLOYMENT'],
    expected_severity = 'SEV2',
    match_spec = '{
        "root_cause": {
            "service_keys": ["payment"],
            "change_types": ["DEPLOYMENT"],
            "symptom_services": ["payment", "gateway"],
            "hypothesis_class": "bad_deployment"
        },
        "invented_evidence_ids": "hard_fail",
        "autonomy": {"level": 2, "harness": true, "slack": false},
        "action_types": ["ROLLBACK_DEPLOYMENT"],
        "severity": "SEV2"
    }'::jsonb,
    answer_payload = '{
        "injector": "bad_deploy",
        "symptom_services": ["payment", "gateway"],
        "scenario_yaml": "scenarios/definitions/bad_deploy.yaml",
        "vertical": "n9"
    }'::jsonb,
    notes = 'N9 first scored vertical — Level 2 harness; no Slack / Level 3',
    updated_at = now()
WHERE scenario_key = 'bad_deploy';

-- Defense in depth after UPDATE.
REVOKE ALL ON TABLE eval.ground_truth FROM PUBLIC;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_app;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_runner;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO migrator;
