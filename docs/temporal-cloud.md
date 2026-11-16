# Temporal Cloud (O6 / #121)

**Prefer Temporal Cloud** for staging and production-demo. Self-hosted Temporal
(Compose `temporal` service or in-cluster Helm) is the **documented fallback**
when Cloud credentials / network are unavailable — not a second production path.

## Hosting modes

| Mode | When | Address sketch | Auth |
| --- | --- | --- | --- |
| `cloud` | staging / production-demo | `<ns>.<account>.tmprl.cloud:7233` | TLS + `TEMPORAL_API_KEY` |
| `selfhosted` | local Compose, kind/k3d, or Cloud blocked | `localhost:7233` / `temporal-frontend:7233` | plaintext (dev) |

Runtime: `shared/incidentpilot_shared/temporal_runtime.py` (`connect_temporal`).
Env: `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TLS`, `TEMPORAL_API_KEY`,
`TEMPORAL_HOSTING`.

## Secrets

Terraform placeholder (never commit real keys):

- Secrets Manager: `${name_prefix}/temporal/cloud`
  JSON: `{ "address", "namespace", "api_key" }`

Sync into a Kubernetes secret for Helm:

```bash
# After filling Secrets Manager (or creating the K8s secret directly):
kubectl -n incidentpilot-system create secret generic incidentpilot-temporal-cloud \
  --from-literal=api_key="$TEMPORAL_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Helm (`config.temporal` in staging / production-demo values):

```yaml
temporal:
  hosting: cloud
  address: <ns>.<acct>.tmprl.cloud:7233
  namespace: <ns>.<acct>
  tls: true
  apiKeySecretName: incidentpilot-temporal-cloud
  apiKeySecretKey: api_key
```

## Network

- Self-host: existing NP `allow-temporal-egress` → namespaces labeled
  `incidentpilot.io/allow-temporal=true`
- Cloud: `allow-temporal-cloud-egress` (TCP/7233). Tighten CIDR in an overlay
  when you have stable ranges — see [network-policies.md](network-policies.md)

## Smoke

Local / self-host (Compose Temporal up):

```bash
make temporal-queue-smoke
```

Against Temporal Cloud (credentials in env):

```bash
export TEMPORAL_ADDRESS='<ns>.<acct>.tmprl.cloud:7233'
export TEMPORAL_NAMESPACE='<ns>.<acct>'
export TEMPORAL_API_KEY='...'   # from Secrets Manager; never commit
export TEMPORAL_HOSTING=cloud
make temporal-cloud-smoke
# or: ./scripts/temporal_cloud_smoke.sh
```

`temporal-cloud-smoke` connects with TLS+API key and runs the same queue
subscribe ping as D1. If `TEMPORAL_API_KEY` is unset it exits with guidance to
use the self-host fallback (`make temporal-queue-smoke`).

## Fallback (self-host)

Use when Cloud signup, VPC egress, or API keys are blocked:

1. Set `config.temporal.hosting: selfhosted` and point `address` at in-cluster
   Temporal (or Compose).
2. Clear `apiKeySecretName`; set `tls: false` for local plaintext.
3. Keep documenting the gap in the environment runbook; Cloud remains the
   target for staging/demo once unblocked.

## Related

- Queues / workers: [temporal-queues.md](temporal-queues.md)
- Helm: [helm.md](helm.md)
- Secrets module: [terraform.md](terraform.md)
