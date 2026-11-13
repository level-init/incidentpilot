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

HTTP fetch only. Evidence-worker activities call `append_raw_evidence_with_blob`
with `prometheus_collector` / `loki_collector` / `tempo_collector`. Do **not**
put these URLs on the general worker.

## Blob store (G5)

| Client | Env | Module |
| --- | --- | --- |
| `S3BlobStore` / `resolve_evidence_blob_store` | `S3_ENDPOINT`, `S3_BUCKET_EVIDENCE`, MinIO/`AWS_*` keys | `incidentpilot_adapters.blob` |
| `resolve_ai_artifacts_blob_store` | same endpoint/keys + `S3_BUCKET_AI_ARTIFACTS` | AIInvocation packages (L3) |
| `resolve_postmortem_export_blob_store` | `S3_BUCKET_POSTMORTEM_EXPORTS` | Postmortem export packages (L6) |

Uploads only — no domain SQL. Collectors claim RAW `quality=HIGH` only when
`put` succeeds and `blob_uri` is set; on failure use MEDIUM + hash/external_ref.

## Change sources (G8)

| Adapter | Role | Module |
| --- | --- | --- |
| `ChangeSource` (Protocol) | Read-only `list_changes` / `fetch_change` | `incidentpilot_adapters.changes` |
| `MemoryChangeSource` | In-memory stub for tests | `incidentpilot_adapters.changes` |

**No mutate / deploy / rollback methods** on ChangeSource. Persist via
`upsert_change_command` (`source_ref` → `domain.change.external_ref`).

| Adapter | Role |
| --- | --- |
| `SimChangeSource` | Scenario catalog (deploy/commit/PR/flag/config/scale) for G9 |

Evidence-worker `change_collector` upserts Change then emits `kind=CHANGE`
Evidence. Bad-deploy → payment `DEPLOYMENT` in the collect window.

## LLM providers (H1)

| Adapter | Role | Module |
| --- | --- | --- |
| `LLMProvider` (Protocol) | `complete(request) → LLMResult` | `incidentpilot_adapters.llm` |
| `FakeLLMProvider` | Canned JSON for tests / CI | `incidentpilot_adapters.llm` |
| `GeminiLLMProvider` | Optional local Gemini (N9) | `incidentpilot_adapters.llm` |
| `complete_structured` | Call + pydantic schema + EV-id allow-list | `incidentpilot_adapters.llm` |

**Must not** write `domain.*` (H2: shared `complete_structured_recorded` /
`record_ai_invocation_command` persist `ai_invocation`). Invalid JSON / extra
fields / invented Evidence ids are rejected — prose cannot mutate domain.

Env (general `incidentpilot-worker` only): `LLM_PROVIDER` (default `fake`;
optional `gemini`), `LLM_MODEL`, `LLM_API_KEY` / `GEMINI_API_KEY`. CI stays on
`fake`. Do **not** put LLM keys on evidence- or remediation-worker.

## Slack notifier (K1)

| Adapter | Role | Module |
| --- | --- | --- |
| `SlackNotifier` / `FakeSlackNotifier` / `HttpSlackNotifier` | Outbound `chat.postMessage` | `incidentpilot_adapters.slack` |
| `render_incident_*` | brief / evidence / status / recovery / postmortem templates | `incidentpilot_adapters.slack` |

**BEST_EFFORT** via outbox `slack.notify`. Cred (`SLACK_BOT_TOKEN`) belongs on
`python -m incidentpilot_worker notify` only — **not** in the AI worker env.
K4 threads replies under `domain.slack_incident_thread`. See [docs/slack.md](../docs/slack.md).
