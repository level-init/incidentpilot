"""FastAPI application — IncidentPilot HTTP API."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from incidentpilot_api.auth import reject_spoofed_identity
from incidentpilot_api.routes import eval as eval_routes
from incidentpilot_api.routes import health, human, incidents, resources, webhooks_alerts

app = FastAPI(
    title="IncidentPilot API",
    version="0.1.0",
    description=(
        "Evidence-driven incident-response control plane HTTP surface. "
        "Session identity: Bearer stub tokens (see docs/auth.md); "
        "client-supplied actor_id is rejected. "
        "GroundTruth requires eval entitlement (C3), separate from ops RBAC. "
        "Alertmanager webhooks: /webhooks/alerts/alertmanager (F1–F5)."
    ),
    dependencies=[Depends(reject_spoofed_identity)],
)

app.include_router(health.router)
app.include_router(incidents.router)
app.include_router(resources.router)
app.include_router(human.router)
app.include_router(eval_routes.router)
app.include_router(webhooks_alerts.router)
