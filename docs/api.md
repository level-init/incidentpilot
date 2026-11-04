# HTTP API

## Auth (C1 session identity)

```http
Authorization: Bearer local-dev
```

See [auth.md](auth.md). Do **not** send `actor_id` / `actor` / `decided_by` in bodies.

Stub tokens: `local-dev` (responder), `local-dev-admin`, `local-dev-viewer`.

- Missing/invalid bearer → **401**
- Role not permitted → **403**
- Spoofed identity fields in JSON body → **400**

## Local run

```bash
make bootstrap
make compose-core && make migrate
make api-run
```

```bash
curl -s http://localhost:8000/health
curl -s -H 'Authorization: Bearer local-dev' http://localhost:8000/incidents
curl -s -X POST -H 'Authorization: Bearer local-dev' \
  -H 'Content-Type: application/json' \
  -d '{"title":"demo"}' \
  http://localhost:8000/incidents
```

Published contract: [openapi/openapi.json](../openapi/openapi.json) (`make openapi-export`).

## Alertmanager webhook (F1)

Separate ingress (not Slack HMAC): `POST /webhooks/alerts/alertmanager`.

See [alert-webhooks.md](alert-webhooks.md) for bearer/basic/header secrets and idempotency.
