"""Remediation adapters — privileged outbound execute (J1+)."""

from incidentpilot_adapters.remediation.noop import (
    NoopRemediationAdapter,
    execute_verified,
    request_from_verified,
)
from incidentpilot_adapters.remediation.protocol import (
    RemediationAdapter,
    RemediationRequest,
    RemediationResult,
)

__all__ = [
    "NoopRemediationAdapter",
    "RemediationAdapter",
    "RemediationRequest",
    "RemediationResult",
    "execute_verified",
    "request_from_verified",
]
