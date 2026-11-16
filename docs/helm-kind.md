# kind / k3d chart validation (O7 / #122)

Prove the Helm chart **installs** into a local Kubernetes API before EKS (O8).
Every PR runs this in CI on **kind**. Full image readiness and AWS are out of
scope.

## What CI does

1. Create a kind cluster (`helm/kind-action`)
2. `make helm-validate` — lint + template all env values
3. `./scripts/helm_kind_smoke.sh` — pre-create namespaces, then
   `helm upgrade --install` with `values-local.yaml` + `values-kind-ci.yaml`
   (`namespace.create: false` so Helm does not hit “already exists”), assert
   Deployments / Services / SAs / namespaces

Pods may `ImagePullBackOff` (GHCR digests not built in this job). The smoke
uses `--wait=false` and checks **API objects**, not Ready.

## Local

```bash
# kind (matches CI)
kind create cluster --name incidentpilot-o7
make helm-validate
make helm-kind-smoke
kind delete cluster --name incidentpilot-o7

# k3d alternative
k3d cluster create incidentpilot-o7
make helm-kind-smoke
k3d cluster delete incidentpilot-o7
```

Optional cleanup inside the script: `HELM_KIND_CLEANUP=1 make helm-kind-smoke`.

## Related

- Chart packaging: [helm.md](helm.md)
- Staging EKS path: O8 / #123
