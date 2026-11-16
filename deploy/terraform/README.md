# Terraform (O1)

AWS IaC skeleton for IncidentPilot cloud demo: **VPC, EKS, RDS, S3, IAM,
Secrets Manager**.

## Layout

```text
deploy/terraform/
├── modules/
│   ├── vpc/        # public + private subnets, NAT, routes
│   ├── eks/        # cluster + default managed node group
│   ├── rds/        # Postgres Multi-AZ staging shape
│   ├── s3/         # evidence + exports buckets
│   ├── iam/        # EKS cluster/node roles
│   ├── irsa/       # Privilege-class IAM roles + OIDC trust (O3)
│   └── secrets/    # Secrets Manager (DB; Slack/OIDC/Temporal Cloud placeholders)
└── environments/
    └── staging/    # staging-shape root module
```

## Validate (no AWS apply)

```bash
make terraform-validate
# or:
./scripts/terraform_validate.sh
```

Requires Terraform ≥ 1.5. Does **not** call AWS APIs (`init -backend=false` +
`fmt -check` + `validate`).

## Staging apply path (reviewed)

O1 documents the path; it does **not** authorize unreviewed expensive applies.

1. Install Terraform ≥ 1.5 and configure AWS credentials for a **staging** account.
2. `cd deploy/terraform/environments/staging`
3. `cp terraform.tfvars.example terraform.tfvars` and set a unique `name_prefix`.
4. Keep `enable_expensive_resources = false` for a cheap IAM/Secrets-only plan.
5. Review: `terraform init && terraform plan`
6. Only after review, set `enable_expensive_resources = true` and re-plan before
   `terraform apply`.

Remote state backend is left commented for O8.

## Privilege classes

IAM module creates separate roles for `api`, `worker`, `evidence`,
`remediation`, `runner`, `evaluator` — **no shared admin SA**. OIDC/IRSA trust
policies are O3.

Docs: [docs/terraform.md](../../docs/terraform.md).
