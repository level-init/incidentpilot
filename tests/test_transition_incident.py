"""B5: TransitionIncident legal edges, illegal edges, stale revision."""

from __future__ import annotations

from uuid import uuid4

import pytest

from incidentpilot_shared.domain import (
    IllegalTransitionError,
    IncidentState,
    StaleRevisionError,
    transition_incident,
)


def test_happy_path_detected_to_closed() -> None:
    incident_id = uuid4()
    path = [
        IncidentState.DETECTED,
        IncidentState.TRIAGING,
        IncidentState.INVESTIGATING,
        IncidentState.DIAGNOSED,
        IncidentState.AWAITING_APPROVAL,
        IncidentState.MITIGATING,
        IncidentState.VALIDATING,
        IncidentState.RECOVERED,
        IncidentState.RESOLVED,
        IncidentState.POSTMORTEM,
        IncidentState.CLOSED,
    ]
    revision = 1
    for from_state, to_state in zip(path, path[1:], strict=False):
        result = transition_incident(
            incident_id=incident_id,
            current_state=from_state,
            expected_revision=revision,
            actual_revision=revision,
            to_state=to_state,
        )
        assert result.from_state == from_state
        assert result.to_state == to_state
        assert result.new_revision == revision + 1
        revision = result.new_revision


def test_reject_validating_to_mitigating() -> None:
    with pytest.raises(IllegalTransitionError, match="VALIDATING → MITIGATING"):
        transition_incident(
            incident_id=uuid4(),
            current_state=IncidentState.VALIDATING,
            expected_revision=3,
            actual_revision=3,
            to_state=IncidentState.MITIGATING,
        )


def test_reject_resolved_to_closed_skip_postmortem() -> None:
    with pytest.raises(IllegalTransitionError, match="RESOLVED → CLOSED"):
        transition_incident(
            incident_id=uuid4(),
            current_state=IncidentState.RESOLVED,
            expected_revision=1,
            actual_revision=1,
            to_state=IncidentState.CLOSED,
        )


def test_stale_revision() -> None:
    with pytest.raises(StaleRevisionError, match="expected 2, actual 5"):
        transition_incident(
            incident_id=uuid4(),
            current_state=IncidentState.INVESTIGATING,
            expected_revision=2,
            actual_revision=5,
            to_state=IncidentState.DIAGNOSED,
        )


def test_diagnosed_may_go_autonomous_mitigating() -> None:
    result = transition_incident(
        incident_id=uuid4(),
        current_state=IncidentState.DIAGNOSED,
        expected_revision=1,
        actual_revision=1,
        to_state=IncidentState.MITIGATING,
    )
    assert result.to_state is IncidentState.MITIGATING
    assert result.new_revision == 2


def test_closed_is_terminal() -> None:
    with pytest.raises(IllegalTransitionError):
        transition_incident(
            incident_id=uuid4(),
            current_state=IncidentState.CLOSED,
            expected_revision=1,
            actual_revision=1,
            to_state=IncidentState.POSTMORTEM,
        )
