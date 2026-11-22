# Staging EKS ephemeral path (O8 / #123)

Exercise the **real AWS path** (IRSA / RDS / S3 / Secrets) without an always-on
cluster. Apply → smoke → **destroy the same day**.

Kind/CI chart install remains O7 ([helm-kind.md](helm-kind.md)). This runbook is
operator-driven; it is not a PR gate.

## Prerequisites

| Item | Notes |
| --- | --- |
| AWS staging account | Billing alarm recommended |
| Terraform ≥ 1.5 | `make terraform-validate` first |
| AWS credentials | `AWS_PROFILE` or env keys with IAM/EKS/RDS/S3/Secrets |
| Unique `name_prefix` | e.g. `ip-stg-$(whoami)-$(date +%Y%m%d)` (S3 global) |
| Optional: S3 remote state | See `backend.hcl.example` |

## 1. Apply (ephemeral)

```bash
cd deploy/terraform/environments/staging
cp terraform.tfvars.example terraform.tfvars
# edit: name_prefix, aws_region; never commit terraform.tfvars

# Optional remote state (recommended for shared staging):
#   aws s3 mb s3://YOUR-TFSTATE-BUCKET
#   cp backend.hcl.example backend.hcl   # fill bucket/key/region
#   terraform init -backend-config=backend.hcl

terraform init
terraform plan

# Cheap skeleton only (IAM + Secrets + IRSA roles pending OIDC):
#   enable_expensive_resources = false

# Full staging shape (VPC/EKS/RDS/S3) — costly; tear down after smoke:
#   enable_expensive_resources = true
terraform apply
```

Flip `enable_expensive_resources` only after reviewing the plan. Outputs of
interest:

```bash
terraform output secrets_arns
terraform output irsa_privilege_class_role_arns
terraform output irsa_enabled
terraform output eks_cluster_name
terraform output rds_endpoint
terraform output s3_bucket_ids
```

Wire Helm IRSA annotations from `irsa_privilege_class_role_arns` —
[identity-irsa.md](identity-irsa.md). Temporal Cloud key stays in Secrets Manager
— [temporal-cloud.md](temporal-cloud.md).

## 2. Smoke checklist

Automated (after apply, from repo root):

```bash
make staging-eks-smoke
# or: ./scripts/staging_eks_smoke.sh
```

Manual checklist (full expensive stack):

- [ ] `secrets_arns` includes `db_master`, `slack_bot`, `oidc`, `temporal_cloud`
- [ ] `irsa_privilege_class_role_arns` has api/worker/evidence/remediation/web/evaluator/runner
- [ ] `irsa_enabled` is `true` (OIDC provider attached after EKS)
- [ ] `eks_cluster_name` set; `aws eks update-kubeconfig --name …` works
- [ ] `rds_endpoint` reachable from private path / SG allows VPC CIDR
- [ ] `s3_bucket_ids` evidence + exports exist; public access blocked
- [ ] Optional: `kubectl apply -k deploy/k8s/identity` + Helm install with IRSA ARNs

Cheap-only apply (`enable_expensive_resources=false`) still exercises **Secrets +
IRSA role objects** (`irsa_enabled=false` until EKS exists). RDS/S3/EKS checks
are skipped with a clear message.

## 3. Teardown

**Do not leave the expensive stack running overnight.**

```bash
make staging-eks-teardown
# or: ./scripts/staging_eks_teardown.sh
#
# Equivalent:
#   cd deploy/terraform/environments/staging
#   terraform destroy
```

Confirm empty:

```bash
terraform state list   # should be empty after destroy
aws eks list-clusters  # no leftover cluster with your name_prefix
```

If destroy fails on non-empty S3, buckets use `force_destroy=true` in the module;
re-run destroy after clearing versions if a prior apply used a different flag.

## Cost / safety

- Default `enable_expensive_resources=false` keeps casual plans cheap
- Unique `name_prefix` avoids clobbering shared staging
- Ephemeral = same-day destroy; O11 covers longer-lived cost controls
- Never commit `terraform.tfvars`, `backend.hcl`, or API keys

## Related

- Modules: [terraform.md](terraform.md)
- IRSA: [identity-irsa.md](identity-irsa.md)
- Helm staging values: [helm.md](helm.md)
