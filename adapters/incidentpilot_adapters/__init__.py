"""Outbound / inbound adapter package for IncidentPilot integrations.

Inbound alert adapters normalize vendor payloads only — they must not write
``domain.*`` (use shared commands from API/workers).
"""

from incidentpilot_adapters.alerts import (
    AlertmanagerAdapter,
    AlertProvider,
    CloudWatchAdapter,
)
from incidentpilot_adapters.blob import (
    BlobStore,
    BlobStoreError,
    FailingBlobStore,
    MemoryBlobStore,
    S3BlobStore,
    resolve_evidence_blob_store,
)
from incidentpilot_adapters.changes import ChangeSource, MemoryChangeSource, SimChangeSource
from incidentpilot_adapters.llm import (
    FakeLLMProvider,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResult,
    StructuredOutputError,
    complete_structured,
    resolve_llm_provider,
)
from incidentpilot_adapters.remediation import (
    RECONCILE_APPLIED,
    RECONCILE_NOT_APPLIED,
    RECONCILE_PARTIAL,
    RECONCILE_UNKNOWN,
    BlindRetryForbidden,
    LostAckError,
    NoopRemediationAdapter,
    RemediationAdapter,
    RemediationRequest,
    RemediationResult,
    SimConfigRestoreAdapter,
    SimDeploymentWorld,
    SimFeatureFlagAdapter,
    SimFlagConfigWorld,
    SimRestartAdapter,
    SimRollbackAdapter,
    SimScaleAdapter,
    SimWorkloadWorld,
    execute_verified,
    reconcile_verified,
    request_from_verified,
)
from incidentpilot_adapters.telemetry import (
    LokiClient,
    PrometheusClient,
    TempoClient,
)

__version__ = "0.0.0"

__all__ = [
    "AlertProvider",
    "AlertmanagerAdapter",
    "BlobStore",
    "BlobStoreError",
    "ChangeSource",
    "CloudWatchAdapter",
    "FailingBlobStore",
    "FakeLLMProvider",
    "LLMMessage",
    "LLMProvider",
    "LLMRequest",
    "LLMResult",
    "LokiClient",
    "MemoryBlobStore",
    "MemoryChangeSource",
    "BlindRetryForbidden",
    "LostAckError",
    "NoopRemediationAdapter",
    "PrometheusClient",
    "RECONCILE_APPLIED",
    "RECONCILE_NOT_APPLIED",
    "RECONCILE_PARTIAL",
    "RECONCILE_UNKNOWN",
    "RemediationAdapter",
    "RemediationRequest",
    "RemediationResult",
    "SimChangeSource",
    "SimConfigRestoreAdapter",
    "SimDeploymentWorld",
    "SimFeatureFlagAdapter",
    "SimFlagConfigWorld",
    "SimRestartAdapter",
    "SimRollbackAdapter",
    "SimScaleAdapter",
    "SimWorkloadWorld",
    "S3BlobStore",
    "StructuredOutputError",
    "TempoClient",
    "complete_structured",
    "execute_verified",
    "reconcile_verified",
    "request_from_verified",
    "resolve_evidence_blob_store",
    "resolve_llm_provider",
    "__version__",
]
