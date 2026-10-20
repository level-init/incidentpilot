# api (`incidentpilot_api`)

Deployable: **incidentpilot-api** — short-lived HTTP and webhooks (FastAPI).

**Owns (later):** REST/OpenAPI surface, webhook ingress, session auth endpoint glue.

**Does not own:** Temporal workers, privileged remediation, GroundTruth.
