# Adapter rules (B7)

Outbound integration clients (Slack, GitHub, K8s, cloud APIs) and inbound
alert normalizers (`AlertProvider`).

**Must not:**
- Execute raw SQL against `domain.*` tables
- Call `TransitionIncident` / invent parallel mutation paths
- Bypass `incidentpilot_shared.domain.commands`

Domain mutations go through the shared command layer used by API + workers.

## Alert providers (F2 / F3)

| Adapter | Source | Module |
| --- | --- | --- |
| `AlertmanagerAdapter` | Alertmanager webhook JSON | `incidentpilot_adapters.alerts` |
| `CloudWatchAdapter` | CW alarm / SNS notification | `incidentpilot_adapters.alerts` |

Both return `list[NormalizedAlert]` (same shape). Persistence is
`upsert_alert_command` in the API/worker — adapters only normalize.

## Telemetry clients (G3)

| Client | Env | Module |
| --- | --- | --- |
| `PrometheusClient` | `PROMETHEUS_URL` | `incidentpilot_adapters.telemetry` |
| `LokiClient` | `LOKI_URL` | `incidentpilot_adapters.telemetry` |
| `TempoClient` | `TEMPO_URL` | `incidentpilot_adapters.telemetry` |

HTTP fetch only. Evidence-worker activities call `append_evidence_command`
with `prometheus_collector` / `loki_collector` / `tempo_collector`. Do **not**
put these URLs on the general worker.
