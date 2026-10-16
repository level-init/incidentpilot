# shared (`incidentpilot_shared`)

Shared domain library imported by `api`, `worker`, and `remediation_worker`.

**Owns (later):** domain models, command layer, transition helpers, shared types.

**Does not own:** HTTP routes, Temporal worker process, remediation credentials.
