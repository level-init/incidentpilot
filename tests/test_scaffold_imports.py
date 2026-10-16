"""Smoke tests: scaffold packages import cleanly (A3)."""

from __future__ import annotations


def test_shared_imports() -> None:
    import incidentpilot_shared

    assert incidentpilot_shared.__version__ == "0.0.0"


def test_api_imports() -> None:
    import incidentpilot_api

    assert incidentpilot_api.__version__ == "0.0.0"


def test_worker_imports() -> None:
    import incidentpilot_worker

    assert incidentpilot_worker.__version__ == "0.0.0"


def test_remediation_imports() -> None:
    import incidentpilot_remediation

    assert incidentpilot_remediation.__version__ == "0.0.0"


def test_adapters_imports() -> None:
    import incidentpilot_adapters

    assert incidentpilot_adapters.__version__ == "0.0.0"


def test_scenario_runner_imports() -> None:
    import incidentpilot_scenario_runner

    assert incidentpilot_scenario_runner.__version__ == "0.0.0"


def test_evaluator_imports() -> None:
    import incidentpilot_evaluator

    assert incidentpilot_evaluator.__version__ == "0.0.0"
