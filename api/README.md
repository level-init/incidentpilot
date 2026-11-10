# api (`incidentpilot_api`)

Deployable: **incidentpilot-api** — short-lived HTTP and webhooks (FastAPI).

**Owns:** REST/OpenAPI surface, webhook ingress (Alertmanager + Slack HMAC),
session auth endpoint glue. ``SLACK_SIGNING_SECRET`` is **api-only** (K2).

**Does not own:** Temporal workers, privileged remediation, GroundTruth,
outbound Slack bot token (notify process).
