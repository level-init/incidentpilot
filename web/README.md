# web (`incidentpilot-web`)

Ops / admin dashboard (Next.js App Router). Framework choice locked in M1 (#87).

## Local

API must be running (`make api-run`, typically `:8000`) with stub auth.

```bash
cd web
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm install
npm run dev                  # http://localhost:3000
```

Or from repo root: `make web-dev`.

Sign in with a stub persona (`local-dev` responder, `local-dev-admin`,
`local-dev-viewer`). The shell calls `GET /auth/me` and stores the Bearer token
in `sessionStorage`.

- **Ops nav** — visible for every authenticated role (starts with Incidents).
- **Admin nav** — only when `role === admin`.
- **Eval UI** — intentionally omitted (C3 / later epic).
- **`/incidents`** — overview metrics + filterable list (severity / state /
  service / duration) via `GET /incidents` (M2).
- **`/incidents/[id]`** — detail header (id / state / severity / env) +
  timeline pane (M3); Evidence vs Hypotheses panes with provenance (M4);
  Impact / Changes / Runbook (authority vs untrusted prose) (M6);
  Remediation panel with approve/reject + UNKNOWN unsafe-to-retry (M5).

Port **3000** matches `INCIDENTPILOT_WEB_BASE_URL` deep links. If Compose
Grafana is also on 3000 (evidence profile), stop Grafana or remap one of them.

## Auth contract

Same as the API: `Authorization: Bearer <token>` only. See [docs/auth.md](../docs/auth.md)
and [docs/web.md](../docs/web.md).
