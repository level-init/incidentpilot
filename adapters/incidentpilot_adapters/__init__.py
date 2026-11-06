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
    "LokiClient",
    "MemoryBlobStore",
    "MemoryChangeSource",
    "PrometheusClient",
    "SimChangeSource",
    "S3BlobStore",
    "TempoClient",
    "resolve_evidence_blob_store",
    "__version__",
]
