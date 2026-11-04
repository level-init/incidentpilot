"""Alert provider normalization (F2+)."""

from incidentpilot_shared.alerts.alertmanager import (
    incidentpilot_fingerprint,
    normalize_alertmanager_webhook,
)
from incidentpilot_shared.alerts.cloudwatch import (
    cloudwatch_fingerprint,
    normalize_cloudwatch_payload,
)
from incidentpilot_shared.alerts.types import NormalizedAlert

__all__ = [
    "NormalizedAlert",
    "cloudwatch_fingerprint",
    "incidentpilot_fingerprint",
    "normalize_alertmanager_webhook",
    "normalize_cloudwatch_payload",
]
