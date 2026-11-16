# NetworkPolicies (O4 / #119)

Default-deny + explicit allowlists. GroundTruth must stay unreachable from
IncidentPilot **workers / api / remediation** over the network — not only via
DB grants and IRSA.

## Planes

| Namespace | Plane label | Role |
| --- | --- | --- |
| `incidentpilot-system` | `incidentpilot.io/plane=control` | api, worker, evidence, remediation, web |
| `incidentpilot-eval` | `incidentpilot.io/plane=eval` | evaluator, runner |

There is **no** NetworkPolicy that allows `incidentpilot-system` →
`incidentpilot-eval` (ingress or egress). Eval ingress is intra-namespace only.

## Manifests

```bash
kubectl apply -k deploy/k8s/identity
kubectl apply -k deploy/k8s/networkpolicies
```

| File | Purpose |
| --- | --- |
| `system-default-deny.yaml` | Deny all ingress/egress in control plane |
| `system-allowlists.yaml` | DNS, Temporal, Postgres, intra-system, API/web ingress |
| `eval-default-deny.yaml` | Deny all ingress/egress in eval plane |
| `eval-allowlists.yaml` | DNS, evaluator→Postgres, runner→Temporal, intra-eval |

### Peer namespace labels (operators)

Allowlisted peers must carry labels (Temporal / Postgres / ingress installs):

| Label | Meaning |
| --- | --- |
| `incidentpilot.io/allow-temporal: "true"` | Temporal frontend namespace (self-host) |
| `incidentpilot.io/allow-postgres: "true"` | Postgres / RDS proxy namespace |
| `incidentpilot.io/allow-ingress: "true"` | Ingress controller namespace |

Temporal Cloud (O6) also has `allow-temporal-cloud-egress` (TCP/7233). See
[temporal-cloud.md](temporal-cloud.md).

## Pod identity

Helm pods carry `incidentpilot.io/privilege-class` (same as SA labels) so
allowlists can select api/worker/evaluator without shared admin.

## Verify

```bash
pytest tests/test_network_policies_o4.py -q
kubectl kustomize deploy/k8s/networkpolicies | grep -c NetworkPolicy
# expect default-deny on both namespaces; no system→eval allow
```

## Related

- Identity / IRSA: [identity-irsa.md](identity-irsa.md)
- DB/GT isolation: [isolation.md](isolation.md)
- Helm workloads: [helm.md](helm.md)
