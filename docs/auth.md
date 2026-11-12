# Session identity (C1)

Human provenance (`actor_id`) is bound from the **authenticated session only**.
Clients must never send `actor_id`, `actor`, `decided_by`, or `observed_by` in
JSON bodies — those fields are rejected with **400**.

## Contract (stub and OIDC)

| Field | Meaning |
| --- | --- |
| `actor_id` | Stable subject id from the session |
| `role` | Ops role (viewer / responder / admin) — see RBAC below |
| `auth_mode` | `stub` or `oidc` |
| `email` | Optional |

HTTP: `Authorization: Bearer <token>` only. Identity headers like `X-Actor` are
**not** authoritative and are ignored.

## Local stub (`AUTH_MODE=stub`, default)

| Bearer token | `actor_id` | ops role | `eval_entitled` |
| --- | --- | --- | --- |
| `local-dev` | `user_local_dev` | responder | no |
| `local-dev-admin` | `user_local_admin` | admin | no |
| `local-dev-viewer` | `user_local_viewer` | viewer | no |
| `local-dev-evaluator` | `user_local_evaluator` | viewer | **yes** |

```bash
curl -s -H 'Authorization: Bearer local-dev' http://localhost:8000/auth/me
curl -s -H 'Authorization: Bearer local-dev' http://localhost:8000/incidents
```

`GET /auth/me` returns the session principal (`actor_id`, `role`, `auth_mode`,
`email`, `eval_entitled`) for the web shell (M1). There is no cookie login —
the UI stores the Bearer token and sends it on each request.

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
  `provenance.actor_id` = session (K5; Responder+; not absolute truth)
- `POST /approvals/{id}/decide` → `decided_by` = session `actor_id`;
  body must include `action_version` (M10 stale guard)
- `POST /eval/approvals/{id}/decide` (I6 harness) → `decided_by = harness:<actor_id>`;
  requires `eval_entitled` (ops Responder alone → **403**)

## Ops RBAC (C2)

| Permission | Viewer | Responder | Admin |
| --- | --- | --- | --- |
| `incident:read` | ✓ | ✓ | ✓ |
| `incident:write` | | ✓ | ✓ |
| `observation:write` | | ✓ | ✓ |
| `approval:decide` | | ✓ | ✓ |
| `admin:config` | | | ✓ |

**Non-negotiable:** a `PolicyDecision` of `BLOCK` cannot be approved by anyone,
including Admin. Approval is only allowed when policy is `REQUIRE_APPROVAL`.

Stub tokens map to roles (table above). Implementation: `api/incidentpilot_api/rbac.py`.

## Eval entitlement (C3) — separate authz domain

GroundTruth / answer-key APIs use `principal.eval_entitled`, **not** ops role.

| Who | `GET /eval/ground-truth` |
| --- | --- |
| Responder / Admin (ops only) | **403** |
| Evaluator stub (`local-dev-evaluator`) | **200** (uses `ip_evaluator` DB role) |

Ops Admin does **not** imply eval access. DB isolation (`ip_app` / `ip_runner`
denied on `eval.ground_truth`) remains the second line of defense — see
[ground-truth.md](ground-truth.md) (N2).

## Swap stub → OIDC (`AUTH_MODE=oidc`)

1. Set `AUTH_MODE=oidc` plus IdP settings (issuer, audience, JWKS URL) — wiring
   lands when OIDC is enabled; today oidc mode returns **501** by design.
2. Keep the same `Principal` shape: validate JWT → map `sub` → `actor_id`,
   map groups/claims → `role`.
3. No API handler changes required for provenance: they already read
   `principal.actor_id` from `get_principal()`.

Until OIDC is wired, leave `AUTH_MODE=stub` for local Compose.
