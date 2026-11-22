# Ingress split: user/API vs webhooks (O5 / #120)

Humans and providers use **different auth models**. Do not put OIDC in front of
Alertmanager / Slack / GitHub webhooks, and do not put webhook secrets on the
user UI/API edge.

## Planes

| Ingress | Hosts (staging sketch) | Auth | Backend |
| --- | --- | --- | --- |
| `*-user` | `staging…`, `api.staging…` | OIDC / oauth2-proxy annotations | web + api |
| `*-webhooks` | `hooks.staging…` | **None at Ingress** — app secrets (F1/K2) | api `/webhooks` |

Labels: `incidentpilot.io/ingress-class=user|webhooks`.

## Allowed webhook paths

Point providers only at the **webhooks** host:

| Path | Provider |
| --- | --- |
| `POST /webhooks/alerts/alertmanager` | Alertmanager (bearer/basic/header) |
| `POST /webhooks/slack/interactions` | Slack HMAC |
| `POST /webhooks/slack/commands` | Slack HMAC |
| `POST /webhooks/github/…` | Reserved (GitHub); not wired yet |

Human session Bearer / OIDC stays on the **user** hosts — see [auth.md](auth.md).
Webhook secret config: [alert-webhooks.md](alert-webhooks.md), [slack.md](slack.md).
Operator recipes: [connect-your-stack.md](connect-your-stack.md).

## Helm

```bash
# Render (staging / production-demo enable ingress by default)
helm template ip-staging deploy/helm/incidentpilot -f deploy/helm/incidentpilot/values-staging.yaml \
  | grep -A2 'ingress-class'

make helm-validate
pytest tests/test_ingress_split_o5.py -q
```

Values live under `ingress.user` / `ingress.webhooks` in
`deploy/helm/incidentpilot/values.yaml`. Shared TLS/class annotations are
optional; **OIDC annotations must only appear on `ingress.user`**.

## Verify (cluster)

```bash
kubectl -n incidentpilot-system get ingress
kubectl -n incidentpilot-system describe ingress -l incidentpilot.io/ingress-class=user
kubectl -n incidentpilot-system describe ingress -l incidentpilot.io/ingress-class=webhooks

# Webhook host: no OIDC challenge; app returns 401/503 without secret
curl -sS -o /dev/null -w '%{http_code}\n' \
  -X POST https://hooks.staging.incidentpilot.example/webhooks/alerts/alertmanager

# User API host: oauth2-proxy / IdP gate (not webhook token)
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://api.staging.incidentpilot.example/auth/me
```

## Related

- Helm packaging: [helm.md](helm.md)
- NetworkPolicies (ingress controller peer label): [network-policies.md](network-policies.md)
