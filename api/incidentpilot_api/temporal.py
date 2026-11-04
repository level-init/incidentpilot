"""Temporal client access for the HTTP API (F5)."""

from __future__ import annotations

from temporalio.client import Client

from incidentpilot_shared.incident_workflow import ensure_incident_workflow_started
from incidentpilot_shared.temporal_runtime import connect_temporal

# Tests may replace this with WorkflowEnvironment.client.
_client_override: Client | None = None
_cached_client: Client | None = None


def set_temporal_client_override(client: Client | None) -> None:
    """Inject a Temporal client (test WorkflowEnvironment)."""
    global _client_override
    _client_override = client


async def get_temporal_client() -> Client:
    global _cached_client
    if _client_override is not None:
        return _client_override
    if _cached_client is None:
        _cached_client = await connect_temporal()
    return _cached_client


async def start_incident_workflows(incident_ids: list) -> None:
    """Idempotent start for each unique incident id (post-commit webhook)."""
    if not incident_ids:
        return
    client = await get_temporal_client()
    seen: set[str] = set()
    for iid in incident_ids:
        key = str(iid)
        if key in seen:
            continue
        seen.add(key)
        await ensure_incident_workflow_started(client, key)
