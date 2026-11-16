# Terraform skeleton (O1 / #116)

Cloud demo uses real IaC patterns under `deploy/terraform/`.

## Modules

| Module | Responsibility |
| --- | --- |
| `vpc` | Staging-shape VPC, public/private subnets, IGW, NAT, routes |
| `eks` | EKS control plane + default managed node group |
| `rds` | Encrypted Postgres, Multi-AZ flag, private subnets |
| `s3` | `evidence` + `exports` buckets (SSE, versioning, public access blocked) |
| `iam` | EKS cluster/node roles |
| `irsa` | Privilege-class IAM roles + OIDC trust (O3) |
| `secrets` | Secrets Manager: generated DB master; Slack/OIDC placeholders |

Environment root: `deploy/terraform/environments/staging`.

## Acceptance

- Module layout + variables/outputs present
- `terraform fmt -check` + `terraform validate` pass
- Documented staging apply path (expensive stack gated)

```bash
make terraform-validate
```

## Out of scope (O1)

- Applying expensive prod without review (`enable_expensive_resources` defaults
  **false**)
- Helm charts (O2), IRSA/SA wiring (O3), NetworkPolicies (O4), Temporal Cloud (O6)

## Next

| Issue | Work |
| --- | --- |
| O2 / #117 | Helm charts + per-env values — [helm.md](helm.md) |
| O3 / #118 | Namespaces + SAs + IRSA — [identity-irsa.md](identity-irsa.md) |
| O8 / #123 | Staging EKS ephemeral path + remote state |
