# Session identity (C1)

Human provenance (`actor_id`) is bound from the **authenticated session only**.
Clients must never send `actor_id`, `actor`, `decided_by`, or `observed_by` in
JSON bodies — those fields are rejected with **400**.

## Contract (stub and OIDC)

| Field | Meaning |
| --- | --- |
| `actor_id` | Stable subject id from the session |
| `role` | Ops role (viewer / responder / admin) — full RBAC in C2 |
| `auth_mode` | `stub` or `oidc` |
| `email` | Optional |

HTTP: `Authorization: Bearer <token>` only. Identity headers like `X-Actor` are
**not** authoritative and are ignored.

## Local stub (`AUTH_MODE=stub`, default)

| Bearer token | `actor_id` | role |
| --- | --- | --- |
| `local-dev` | `user_local_dev` | responder |
| `local-dev-admin` | `user_local_admin` | admin |
| `local-dev-viewer` | `user_local_viewer` | viewer |

```bash
curl -s -H 'Authorization: Bearer local-dev' http://localhost:8000/incidents
```

Forged body identity fails:

```bash
curl -s -X POST -H 'Authorization: Bearer local-dev' \
  -H 'Content-Type: application/json' \
  -d '{"title":"x","actor_id":"evil"}' \
  http://localhost:8000/incidents
# → 400 client-supplied identity field(s) forbidden
```

Session identity on human actions:

- `POST /incidents/{id}/observations` → Evidence `HUMAN_OBSERVATION` with
  `provenance.actor_id` = session
- `POST /approvals/{id}/decide` → `decided_by` = session `actor_id`

## Swap stub → OIDC (`AUTH_MODE=oidc`)

1. Set `AUTH_MODE=oidc` plus IdP settings (issuer, audience, JWKS URL) — wiring
   lands when OIDC is enabled; today oidc mode returns **501** by design.
2. Keep the same `Principal` shape: validate JWT → map `sub` → `actor_id`,
   map groups/claims → `role`.
3. No API handler changes required for provenance: they already read
   `principal.actor_id` from `get_principal()`.

Until OIDC is wired, leave `AUTH_MODE=stub` for local Compose.
