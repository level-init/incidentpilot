"""Deterministic evidence processors (G4)."""

from incidentpilot_shared.processors.baseline import (
    RULE_BASELINE_COMPARE,
    baseline_compare,
)
from incidentpilot_shared.processors.top_errors import (
    RULE_TOP_ERRORS,
    top_errors,
)

__all__ = [
    "RULE_BASELINE_COMPARE",
    "RULE_TOP_ERRORS",
    "baseline_compare",
    "top_errors",
]
