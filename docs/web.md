# Web dashboard (M1 / M2)

Deployable: **incidentpilot-web** (`web/`). Next.js App Router + TypeScript.

## Login smoke (M1)

1. Start API: `make api-run` (Bearer stub mode).
2. Start UI: `make web-dev` → http://localhost:3000
3. Choose **Responder** (`local-dev`) → Continue.
4. Confirm **IncidentPilot** shell with **Ops → Incidents**.
5. Sign out; choose **Admin** (`local-dev-admin`) → confirm **Admin** nav appears.
6. Responder must not see Admin nav.

Session probe used by the UI:

```bash
curl -s -H 'Authorization: Bearer local-dev' http://localhost:8000/auth/me
```

## Incident overview + list (M2)

Open `/incidents` after login. The page shows:

- Overview metrics (listed / active / by state / by severity)
- Filters: state, severity, service key
- Table columns: public id, title, **severity**, **state**, **service**, **duration**

List API:

```bash
curl -s -H 'Authorization: Bearer local-dev' \
  'http://localhost:8000/incidents?state=DETECTED&severity=SEV2&service=checkout'
```

`IncidentOut.service_keys` comes from `domain.incident_service`. Duration is
computed in the UI from `opened_at` → `resolved_at` / `closed_at` / now.

## Incident detail skeleton (M3)

Open `/incidents/{public_id}` (UUID also works). Header shows incident id,
live **state**, **severity**, **env** (from linked services), services, and
duration. Timeline pane loads `GET /incidents/{id}/timeline?order=asc`.

```bash
curl -s -H 'Authorization: Bearer local-dev' \
  http://localhost:8000/incidents/<public_id_or_uuid>
curl -s -H 'Authorization: Bearer local-dev' \
  'http://localhost:8000/incidents/<uuid>/timeline?order=asc'
```

## Evidence + Hypotheses panes (M4)

On the detail page, two visually distinct panes sit under the header:

| Pane | Meaning | Look |
| --- | --- | --- |
| **Evidence** | Production facts | Solid teal border; provenance badges (`layer`, `quality`, `truthfulness`, producer, kind) |
| **Hypotheses** | Interpretations | Dashed warm border; italic statements; `score_kind` / status badges |

Hypothesis `cited_evidence_ids` render as navigable links to `#evidence-{id}`.
Responders/Admins get a **HUMAN_OBSERVATION** form (`POST …/observations`);
Viewers see a read-only hint.

```bash
curl -s -H 'Authorization: Bearer local-dev' \
  "http://localhost:8000/evidence?incident_id=<uuid>"
curl -s -H 'Authorization: Bearer local-dev' \
  "http://localhost:8000/hypotheses?incident_id=<uuid>"
```

Remediation panel is out of scope (M5).

## Nav model

| Section | Who sees it | Routes |
| --- | --- | --- |
| Ops | viewer / responder / admin | `/incidents` |
| Admin | admin only | `/admin` |
| Eval | none (out of scope) | — |

Actor identity is never taken from form bodies — only from the Bearer session
resolved by the API (`docs/auth.md`).

## CORS

Browser origin defaults to `http://localhost:3000`. API allows it via
`CORS_ORIGINS` (comma-separated). Override when the UI is hosted elsewhere.
