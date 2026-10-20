# HTTP API (B8)

## Auth stub (until Epic C)

```http
Authorization: Bearer local-dev
X-Actor: optional-name
X-Role: viewer|responder|admin
```

- Missing/invalid bearer → **401**
- Role not permitted for mutation → **403**
- Viewer can list/read; responder/admin can create/transition

## Local run

```bash
make bootstrap
make compose-core && make migrate
make api-run
# http://localhost:8000/docs
# http://localhost:8000/openapi.json
```

```bash
curl -s http://localhost:8000/health
curl -s -H 'Authorization: Bearer local-dev' http://localhost:8000/incidents
curl -s -X POST -H 'Authorization: Bearer local-dev' -H 'X-Role: responder' \
  -H 'Content-Type: application/json' \
  -d '{"title":"demo"}' \
  http://localhost:8000/incidents
```

Published contract: [openapi/openapi.json](../openapi/openapi.json) (`make openapi-export`).
