"""Outbound / inbound adapter package for IncidentPilot integrations.

Inbound alert adapters normalize vendor payloads only — they must not write
``domain.*`` (use shared commands from API/workers).
"""

from incidentpilot_adapters.alerts import (
    AlertmanagerAdapter,
    AlertProvider,
    CloudWatchAdapter,
)

__version__ = "0.0.0"

__all__ = [
    "AlertProvider",
    "AlertmanagerAdapter",
    "CloudWatchAdapter",
    "__version__",
]
