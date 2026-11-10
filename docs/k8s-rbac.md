# K8s RBAC for remediation identities (J11)

Defense in depth: **IP authz** (VerifyExecutionAttempt) + **adapter identity**
(remediation SA) + **narrow K8s RBAC** (this doc). Namespaces organize;
they are not the only security boundary.

## Identities

| Privilege class | ServiceAccount | Namespace | Notes |
| --- | --- | --- | --- |
| remediation | `incidentpilot-remediation` | `incidentpilot-system` | Only SA with mutate RoleBindings |
| (others) | owned by O3 | — | api / worker / evidence / runner / evaluator — **no shared admin SA** |

Manifests: `deploy/k8s/remediation/` + `deploy/k8s/namespaces/`.

**Out of scope:** `cluster-admin` convenience. There is **no** ClusterRole or
ClusterRoleBinding for the remediation identity.

## Approved target namespaces

RoleBindings exist **only** in:

`sim-checkout`, `sim-payment`, `sim-gateway`, `sim-auth`, `sim-inventory`,
`sim-notification`

Mutations outside that allowlist (e.g. `kube-system`, `default`) must be
denied by the apiserver.

## Action → API mapping

| IncidentPilot action | API group | Resources | Verbs |
| --- | --- | --- | --- |
| `ROLLBACK_DEPLOYMENT` | `apps` | `deployments`, `replicasets` | `get`, `list`, `watch`, `patch`, `update` |
| `SCALE_WORKLOAD` | `apps` | `deployments/scale`, `statefulsets`, `statefulsets/scale` | `get`, `list`, `watch`, `patch`, `update` |
| `RESTART_WORKLOAD` | `apps` + `""` | deployment annotation patch via `deployments`; or `pods` delete | `patch`/`update` on deployments; `get`/`list`/`watch`/`delete` on pods |

Not granted: `secrets`, `*` resources, `*` verbs, namespace create, cluster-scoped
mutate, `escalate` / `bind` on RBAC objects.

## Apply (kind / k3d)

```bash
kubectl apply -k deploy/k8s/remediation
```

## Verify (kubeauth)

Static policy tests always run:

```bash
pytest tests/test_k8s_rbac_j11.py
```

Against a live kind/k3d cluster (optional):

```bash
export INCIDENTPILOT_KIND=1
kubectl apply -k deploy/k8s/remediation
pytest tests/test_k8s_rbac_j11.py -k kind
# or manually:
kubectl auth can-i patch deployments.apps \
  --as=system:serviceaccount:incidentpilot-system:incidentpilot-remediation \
  -n sim-checkout
# expect yes
kubectl auth can-i patch deployments.apps \
  --as=system:serviceaccount:incidentpilot-system:incidentpilot-remediation \
  -n kube-system
# expect no
kubectl auth can-i '*' '*' \
  --as=system:serviceaccount:incidentpilot-system:incidentpilot-remediation \
  --all-namespaces
# expect no
```

## Relation to O3

O3 (#118) owns the full namespace + SA + IRSA matrix for every privilege class.
J11 seeds the remediation SA and approved-target RoleBindings so remediation
cannot cluster-admin before Helm/IRSA land.
