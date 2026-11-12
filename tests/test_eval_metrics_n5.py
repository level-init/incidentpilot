"""N5: eval metric engine — formulas + invented citations hard-fail."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "evaluator"))

from incidentpilot_shared.eval_metrics import (  # noqa: E402
    IncidentScoreInput,
    RootCauseMatchSpec,
    evaluate_operational,
    metric_invented_evidence_citations,
    metric_root_cause_match,
    parse_root_cause_match_spec,
)


def test_invented_citations_hard_fail() -> None:
    inp = IncidentScoreInput(
        known_evidence_ids=frozenset({"EV-aaa", "EV-bbb"}),
        cited_evidence_ids=frozenset({"EV-aaa", "EV-invented"}),
    )
    m = metric_invented_evidence_citations(inp)
    assert m.applicable is True
    assert m.hard_fail is True
    assert m.score == 0.0
    assert "EV-invented" in m.detail["invented_ids"]


def test_invented_citations_pass_when_all_known() -> None:
    inp = IncidentScoreInput(
        known_evidence_ids=frozenset({"EV-aaa", "EV-bbb"}),
        cited_evidence_ids=frozenset({"EV-aaa"}),
    )
    m = metric_invented_evidence_citations(inp)
    assert m.hard_fail is False
    assert m.score == 1.0


def test_root_cause_match_partial_recall() -> None:
    spec = RootCauseMatchSpec(
        service_keys=frozenset({"payment", "inventory"}),
        expected_hypothesis_class="cascading_failure",
    )
    inp = IncidentScoreInput(
        confirmed_hypothesis_class="cascading_failure",
        observed_origin_service_keys=frozenset({"payment"}),
    )
    m = metric_root_cause_match(inp, spec)
    assert m.applicable is True
    # class 1.0 + service recall 0.5 → mean 0.75
    assert m.score == 0.75


def test_parse_match_spec_from_gt_shape() -> None:
    spec = parse_root_cause_match_spec(
        {
            "root_cause": {
                "service_keys": ["payment"],
                "change_types": ["DEPLOYMENT"],
            }
        },
        expected_hypothesis_class="bad_deployment",
        origin_service_keys=["payment"],
    )
    assert spec.service_keys == frozenset({"payment"})
    assert spec.change_types == frozenset({"DEPLOYMENT"})
    assert spec.expected_hypothesis_class == "bad_deployment"


def test_evaluate_hard_fail_short_circuits_pass() -> None:
    spec = RootCauseMatchSpec(
        service_keys=frozenset({"payment"}),
        expected_hypothesis_class="bad_deployment",
    )
    inp = IncidentScoreInput(
        confirmed_hypothesis_class="bad_deployment",
        known_evidence_ids=frozenset({"EV-1"}),
        cited_evidence_ids=frozenset({"EV-1", "EV-fake"}),
        observed_origin_service_keys=frozenset({"payment"}),
        executed_action_types=frozenset({"ROLLBACK_DEPLOYMENT"}),
        severity="SEV2",
    )
    result = evaluate_operational(
        inp,
        match_spec=spec,
        expected_action_types=["ROLLBACK_DEPLOYMENT"],
        expected_severity="SEV2",
    )
    assert result.hard_fail is True
    assert result.passed is False
    assert result.score == 0.0
    assert "invented_evidence_citations" in result.summary["failed_metrics"]


def test_evaluate_scored_pass() -> None:
    spec = RootCauseMatchSpec(
        service_keys=frozenset({"payment"}),
        change_types=frozenset({"DEPLOYMENT"}),
        expected_hypothesis_class="bad_deployment",
    )
    inp = IncidentScoreInput(
        confirmed_hypothesis_class="bad_deployment",
        known_evidence_ids=frozenset({"EV-1", "EV-2"}),
        cited_evidence_ids=frozenset({"EV-1"}),
        observed_origin_service_keys=frozenset({"payment"}),
        observed_change_types=frozenset({"DEPLOYMENT"}),
        executed_action_types=frozenset({"ROLLBACK_DEPLOYMENT"}),
        severity="SEV2",
    )
    result = evaluate_operational(
        inp,
        match_spec=spec,
        expected_action_types=["ROLLBACK_DEPLOYMENT"],
        expected_severity="SEV2",
        threshold=0.7,
    )
    assert result.hard_fail is False
    assert result.passed is True
    assert result.score is not None and result.score >= 0.7


def test_evaluate_scored_fail_without_hard_fail() -> None:
    """Valid env, wrong diagnosis → passed=false (distinct from ScenarioRun FAILED)."""
    spec = RootCauseMatchSpec(
        service_keys=frozenset({"payment"}),
        expected_hypothesis_class="bad_deployment",
    )
    inp = IncidentScoreInput(
        confirmed_hypothesis_class="wrong_class",
        known_evidence_ids=frozenset({"EV-1"}),
        cited_evidence_ids=frozenset({"EV-1"}),
        observed_origin_service_keys=frozenset({"auth"}),
        executed_action_types=frozenset({"SCALE_WORKLOAD"}),
        severity="SEV3",
    )
    result = evaluate_operational(
        inp,
        match_spec=spec,
        expected_action_types=["ROLLBACK_DEPLOYMENT"],
        expected_severity="SEV2",
        threshold=0.7,
    )
    assert result.hard_fail is False
    assert result.passed is False
    assert result.score is not None and result.score < 0.7


def test_no_llm_wording_metric_exported() -> None:
    import incidentpilot_shared.eval_metrics as m
    import incidentpilot_shared.eval_metrics.engine as eng

    names = set(dir(m)) | set(dir(eng))
    assert not any("wording" in n.lower() or "bleu" in n.lower() for n in names)
    assert not any("embedding" in n.lower() for n in names)
