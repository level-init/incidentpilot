# remediation_worker (`incidentpilot_remediation`)

Deployable: **remediation-worker** — privileged execute / reconcile only.

**Owns (later):** RemediationAdapter calls, attempt verification, narrow identity.

**Does not own:** investigation reasoning, GroundTruth, user-facing HTTP.
