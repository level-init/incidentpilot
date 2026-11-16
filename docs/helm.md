# Helm charts (O2 / #117)

App packaging for Kubernetes lives under `deploy/helm/incidentpilot/`.

J11 remediation **RBAC** manifests stay in `deploy/k8s/remediation/` (narrow
RoleBindings). This chart deploys workloads; it does not dual-maintain
Kustomize for the same Deployments.

## Chart

| Path | Role |
| --- | --- |
| `Chart.yaml` | Umbrella chart metadata |
| `values.yaml` | Defaults |
| `values.schema.json` | JSON Schema for values (helm validates on lint/template) |
| `values-local.yaml` | kind/k3d / local shape |
| `values-staging.yaml` | Staging EKS shape |
| `values-production-demo.yaml` | production-demo promote target |
| `templates/` | Deployments / Services / ConfigMap / optional Namespace |

### Components

`api`, `worker`, `evidenceWorker`, `remediation`, `web`, `evaluator`,
`scenarioRunner` — each toggled with `enabled` and a dedicated ServiceAccount
(O3 creates SAs; optional `irsa.roleArns` annotations). Pod templates also set
`incidentpilot.io/privilege-class` for NetworkPolicy selection (O4).
Evaluator/runner run in `incidentpilot-eval`. No shared admin SA —
[identity-irsa.md](identity-irsa.md), [network-policies.md](network-policies.md).

## Validate

```bash
make helm-validate
# helm lint + helm template for local, staging, production-demo
```

Requires Helm 3 on `PATH`.

## Install sketch (after O3 SA/IRSA)

```bash
helm upgrade --install ip deploy/helm/incidentpilot \
  -n incidentpilot-system \
  -f deploy/helm/incidentpilot/values-staging.yaml
```

## Next

| Issue | Work |
| --- | --- |
| O3 / #118 | Namespaces + SAs + IRSA |
| O5 / #120 | Ingress split |
| O7 / #122 | kind/k3d chart validation in CI |
