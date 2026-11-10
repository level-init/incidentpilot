# Web dashboard (M1)

Deployable: **incidentpilot-web** (`web/`). Next.js App Router + TypeScript.

## Login smoke

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

## Nav model

| Section | Who sees it | Routes (M1) |
| --- | --- | --- |
| Ops | viewer / responder / admin | `/incidents` |
| Admin | admin only | `/admin` |
| Eval | none (out of scope) | — |

Actor identity is never taken from form bodies — only from the Bearer session
resolved by the API (`docs/auth.md`).

## CORS

Browser origin defaults to `http://localhost:3000`. API allows it via
`CORS_ORIGINS` (comma-separated). Override when the UI is hosted elsewhere.
