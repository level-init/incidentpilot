"""FastAPI application — IncidentPilot HTTP API."""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from incidentpilot_api.auth import reject_spoofed_identity
from incidentpilot_api.routes import (
    ai_invocations,
    auth,
    evidence,
    health,
    history,
    human,
    incidents,
    remediation,
    resources,
    runbooks,
    webhooks_alerts,
    webhooks_slack,
)
from incidentpilot_api.routes import eval as eval_routes

app = FastAPI(
    title="IncidentPilot API",
    version="0.1.0",
    description=(
        "Evidence-driven incident-response control plane HTTP surface. "
        "Session identity: Bearer stub tokens (see docs/auth.md); "
        "client-supplied actor_id is rejected. "
        "GroundTruth requires eval entitlement (C3), separate from ops RBAC. "
        "Alertmanager webhooks: /webhooks/alerts/alertmanager (F1–F5). "
        "Slack interactions: /webhooks/slack/interactions (K2/K3 HMAC); "
        "slash commands: /webhooks/slack/commands (K6)."
    ),
    dependencies=[Depends(reject_spoofed_identity)],
)

# Browser dashboard (M1). Override with CORS_ORIGINS=comma-separated list.
_cors_raw = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
)
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(incidents.router)
app.include_router(resources.router)
app.include_router(evidence.router)
app.include_router(runbooks.router)
app.include_router(history.router)
app.include_router(human.router)
app.include_router(remediation.router)
app.include_router(ai_invocations.router)
app.include_router(eval_routes.router)
app.include_router(webhooks_alerts.router)
app.include_router(webhooks_slack.router)
