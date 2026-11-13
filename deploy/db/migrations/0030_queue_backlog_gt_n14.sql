-- N14 / #111: Tighten queue_backlog GroundTruth for scored scenario.
-- Evaluator-only; ip_app / ip_runner still cannot SELECT.

UPDATE eval.ground_truth
SET
    version = 2,
    title = 'Queue backlog',
    origin_service_keys = ARRAY['notification'],
    expected_hypothesis_class = 'queue_backlog',
    expected_action_types = ARRAY['SCALE_WORKLOAD'],
    expected_severity = 'SEV3',
    match_spec = '{
        "root_cause": {
            "service_keys": ["notification"],
            "symptom_services": ["notification"],
            "hypothesis_class": "queue_backlog"
        },
        "invented_evidence_ids": "hard_fail",
        "autonomy": {"level": 2, "harness": true, "slack": false},
        "action_types": ["SCALE_WORKLOAD"],
        "severity": "SEV3"
    }'::jsonb,
    answer_payload = '{
        "injector": "queue_backlog",
        "symptom_services": ["notification"],
        "scenario_yaml": "scenarios/definitions/queue_backlog.yaml",
        "vertical": "n14"
    }'::jsonb,
    notes = 'N14 scored scenario — Level 2 harness SCALE_WORKLOAD; no Slack / Level 3',
    updated_at = now()
WHERE scenario_key = 'queue_backlog';

REVOKE ALL ON TABLE eval.ground_truth FROM PUBLIC;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_app;
REVOKE ALL ON TABLE eval.ground_truth FROM ip_runner;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO ip_evaluator;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eval.ground_truth TO migrator;
