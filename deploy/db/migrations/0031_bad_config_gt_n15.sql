-- N15 / #112: Tighten bad_config GroundTruth for scored scenario.
-- Replaces invalid TOGGLE_FEATURE_FLAG seed with DISABLE_FEATURE_FLAG (domain SoR).
-- Evaluator-only; ip_app / ip_runner still cannot SELECT.

UPDATE eval.ground_truth
SET
    version = 2,
    title = 'Bad configuration / feature flag',
    origin_service_keys = ARRAY['auth'],
    expected_hypothesis_class = 'bad_config',
    expected_action_types = ARRAY['DISABLE_FEATURE_FLAG'],
    expected_severity = 'SEV2',
    match_spec = '{
        "root_cause": {
            "service_keys": ["auth"],
            "change_types": ["FEATURE_FLAG"],
            "symptom_services": ["auth", "gateway"],
            "hypothesis_class": "bad_config"
        },
        "invented_evidence_ids": "hard_fail",
        "autonomy": {"level": 2, "harness": true, "slack": false},
        "action_types": ["DISABLE_FEATURE_FLAG"],
        "alternate_action_types": ["RESTORE_CONFIG", "RESTORE_FEATURE_FLAG"],
        "severity": "SEV2"
    }'::jsonb,
    answer_payload = '{
        "injector": "bad_config",
        "symptom_services": ["auth", "gateway"],
        "scenario_yaml": "scenarios/definitions/bad_config.yaml",
        "vertical": "n15"
    }'::jsonb,
    notes = 'N15 scored scenario — Level 2 harness DISABLE_FEATURE_FLAG; no Slack / Level 3',
    updated_at = now()
WHERE scenario_key = 'bad_config';

REVOKE ALL ON TABLE eval.ground_truth FROM PUBLIC;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_app;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_runner;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO migrator;
