-- N16 / #113: Tighten cascading_failure GroundTruth for scored scenario.
-- Origin ≠ symptom (payment+inventory vs gateway). Evaluator-only.

UPDATE eval.ground_truth
SET
    version = 2,
    title = 'Cascading failure',
    origin_service_keys = ARRAY['payment', 'inventory'],
    expected_hypothesis_class = 'cascading_failure',
    expected_action_types = ARRAY['ROLLBACK_DEPLOYMENT'],
    expected_severity = 'SEV1',
    match_spec = '{
        "root_cause": {
            "service_keys": ["payment", "inventory"],
            "change_types": ["DEPLOYMENT"],
            "symptom_services": ["gateway"],
            "hypothesis_class": "cascading_failure",
            "origin_ne_symptom": true
        },
        "invented_evidence_ids": "hard_fail",
        "autonomy": {"level": 2, "harness": true, "slack": false},
        "action_types": ["ROLLBACK_DEPLOYMENT"],
        "alternate_action_types": ["REROUTE_TRAFFIC"],
        "severity": "SEV1"
    }'::jsonb,
    answer_payload = '{
        "injector": "cascading_failure",
        "origin_services": ["payment", "inventory"],
        "symptom_services": ["gateway"],
        "origin_ne_symptom": true,
        "scenario_yaml": "scenarios/definitions/cascading_failure.yaml",
        "vertical": "n16"
    }'::jsonb,
    notes = 'N16 scored scenario — Level 2 ROLLBACK; origin ≠ symptom; no Slack / Level 3',
    updated_at = now()
WHERE scenario_key = 'cascading_failure';

REVOKE ALL ON TABLE eval.ground_truth FROM PUBLIC;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_app;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_runner;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO migrator;
