# Adapter rules (B7)

Outbound integration clients only (Slack, GitHub, K8s, cloud APIs).

**Must not:**
- Execute raw SQL against `domain.*` tables
- Call `TransitionIncident` / invent parallel mutation paths
- Bypass `incidentpilot_shared.domain.commands`

Domain mutations go through the shared command layer used by API + workers.
