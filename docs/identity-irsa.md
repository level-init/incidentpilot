# Namespaces, ServiceAccounts & IRSA (O3 / #118)

One privilege class → one identity. Namespaces organize; they are **not** the
only security boundary.

## Privilege matrix

| Privilege class | Namespace | ServiceAccount | Notes |
| --- | --- | --- | --- |
| api | `incidentpilot-system` | `incidentpilot-api` | HTTP / webhooks |
| worker | `incidentpilot-system` | `incidentpilot-worker` | Temporal general |
| evidence | `incidentpilot-system` | `incidentpilot-evidence` | Evidence collectors |
| remediation | `incidentpilot-system` | `incidentpilot-remediation` | Mutate RoleBindings (J11) |
| web | `incidentpilot-system` | `incidentpilot-web` | Dashboard |
| evaluator | `incidentpilot-eval` | `incidentpilot-evaluator` | GT-capable pin consumer |
| runner | `incidentpilot-eval` | `incidentpilot-runner` | Scenario runner (no GT) |

**No** `incidentpilot-admin` / shared admin SA. **No** `cluster-admin` bindings.

## Manifests

```bash
kubectl apply -k deploy/k8s/identity
kubectl get sa -n incidentpilot-system
kubectl get sa -n incidentpilot-eval
```

Remediation RBAC still: `kubectl apply -k deploy/k8s/remediation` (includes
identity + approved-target RoleBindings).

## IRSA (Terraform)

Module `deploy/terraform/modules/irsa` creates one IAM role per class. When
staging EKS is enabled (`enable_expensive_resources=true`), the root module
registers the cluster OIDC provider and switches trusts to
`AssumeRoleWithWebIdentity` scoped to
`system:serviceaccount:<ns>:<sa>`.

```bash
make terraform-validate
# after apply with EKS:
terraform -chdir=deploy/terraform/environments/staging output irsa_privilege_class_role_arns
```

Annotate Helm values:

```yaml
irsa:
  enabled: true
  roleArns:
    api: arn:aws:iam::…:role/ip-staging-api
    # …
```

Chart templates render `eks.amazonaws.com/role-arn` on each SA.

## Verify

```bash
pytest tests/test_identity_irsa_o3.py tests/test_k8s_rbac_j11.py -q
make helm-validate
make terraform-validate
kubectl get sa -A | grep incidentpilot
# expect seven SAs; never incidentpilot-admin
```

## Related

- J11 remediation RBAC: [k8s-rbac.md](k8s-rbac.md)
- Helm packaging: [helm.md](helm.md)
- Terraform: [terraform.md](terraform.md)
- NetworkPolicies (GT unreachable): [network-policies.md](network-policies.md)
