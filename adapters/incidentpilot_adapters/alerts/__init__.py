"""Inbound alert provider adapters (normalize only — no domain writes)."""

from incidentpilot_adapters.alerts.alertmanager import AlertmanagerAdapter
from incidentpilot_adapters.alerts.cloudwatch import CloudWatchAdapter
from incidentpilot_adapters.alerts.protocol import AlertProvider

__all__ = [
    "AlertProvider",
    "AlertmanagerAdapter",
    "CloudWatchAdapter",
]
