"""FastAPI application — IncidentPilot HTTP API (B8)."""

from __future__ import annotations

from fastapi import FastAPI

from incidentpilot_api.routes import health, incidents, resources

app = FastAPI(
    title="IncidentPilot API",
    version="0.1.0",
    description=(
        "Evidence-driven incident-response control plane HTTP surface. "
        "Auth is a local stub (`Bearer local-dev`) until Epic C."
    ),
)

app.include_router(health.router)
app.include_router(incidents.router)
app.include_router(resources.router)
