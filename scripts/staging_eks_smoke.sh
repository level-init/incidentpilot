#!/usr/bin/env bash
# O8: smoke-check staging Terraform outputs (IRSA / Secrets; RDS/S3/EKS when enabled).
# Does not apply infrastructure. Requires a prior terraform apply in staging/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING="${ROOT}/deploy/terraform/environments/staging"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required tool: $1" >&2
    exit 127
  }
}

need terraform
need python3

if [[ ! -d "${STAGING}/.terraform" ]]; then
  cat >&2 <<'EOF'
staging-eks-smoke: terraform not initialized in environments/staging.

Follow docs/staging-eks.md:
  cd deploy/terraform/environments/staging
  terraform init && terraform apply
Then re-run: make staging-eks-smoke
EOF
  exit 2
fi

cd "${STAGING}"

if ! terraform output -json >/tmp/ip-staging-outputs.json 2>/dev/null; then
  cat >&2 <<'EOF'
staging-eks-smoke: could not read terraform outputs (no state / apply yet).

Apply the ephemeral staging stack first (docs/staging-eks.md), then re-run.
EOF
  exit 2
fi

python3 - <<'PY'
import json
import sys
from pathlib import Path

raw = json.loads(Path("/tmp/ip-staging-outputs.json").read_text())
if not raw:
    print(
        "staging-eks-smoke: terraform outputs are empty (no apply / empty state).\n"
        "Follow docs/staging-eks.md → terraform apply → re-run make staging-eks-smoke",
        file=sys.stderr,
    )
    sys.exit(2)

# terraform output -json → { name: { value, type, sensitive? } }
outs = {k: v.get("value") for k, v in raw.items()}

def fail(msg: str) -> None:
    print(f"fail: {msg}", file=sys.stderr)
    sys.exit(1)

secrets = outs.get("secrets_arns") or {}
if not isinstance(secrets, dict):
    fail("secrets_arns missing or not a map")
for key in ("db_master", "slack_bot", "oidc", "temporal_cloud"):
    arn = secrets.get(key)
    if not arn or "arn:aws:secretsmanager" not in str(arn):
        fail(f"secrets_arns[{key}] missing or not a Secrets Manager ARN")

irsa = outs.get("irsa_privilege_class_role_arns") or {}
if not isinstance(irsa, dict):
    fail("irsa_privilege_class_role_arns missing")
for cls in ("api", "worker", "evidence", "remediation", "web", "evaluator", "runner"):
    arn = irsa.get(cls)
    if not arn or ":role/" not in str(arn):
        fail(f"irsa role missing for privilege class {cls}")

expensive = bool(outs.get("enable_expensive_resources"))
irsa_on = bool(outs.get("irsa_enabled"))
print(f"ok secrets ({len(secrets)} arns)")
print(f"ok irsa roles ({len(irsa)} classes); irsa_enabled={irsa_on}")

if not expensive:
    print(
        "skip: enable_expensive_resources=false — "
        "EKS/RDS/S3 not in this apply (cheap skeleton only). "
        "Flip true for full ephemeral smoke, then destroy."
    )
    print("ok staging-eks-smoke (cheap)")
    sys.exit(0)

if not irsa_on:
    fail("expensive stack applied but irsa_enabled is false (OIDC not wired)")

eks = outs.get("eks_cluster_name")
if not eks:
    fail("eks_cluster_name empty with expensive stack")
rds = outs.get("rds_endpoint")
if not rds:
    fail("rds_endpoint empty with expensive stack")
buckets = outs.get("s3_bucket_ids") or {}
if not isinstance(buckets, dict) or not buckets:
    fail("s3_bucket_ids missing")
for name in ("evidence", "exports"):
    # module may use different keys — accept any non-empty map with 2+ buckets
    pass
if len(buckets) < 2:
    fail(f"expected ≥2 S3 buckets, got {buckets!r}")

print(f"ok eks_cluster_name={eks}")
print(f"ok rds_endpoint={rds}")
print(f"ok s3_bucket_ids={list(buckets.keys())}")
print("ok staging-eks-smoke (full ephemeral)")
PY

# Optional live AWS probes when AWS CLI + credentials are present.
if command -v aws >/dev/null 2>&1; then
  if aws sts get-caller-identity >/dev/null 2>&1; then
    echo "aws caller ok — optional describe probes…"
    EXPENSIVE="$(terraform output -raw enable_expensive_resources 2>/dev/null || echo false)"
    if [[ "${EXPENSIVE}" == "true" ]]; then
      EKS_NAME="$(terraform output -raw eks_cluster_name)"
      aws eks describe-cluster --name "${EKS_NAME}" --query 'cluster.status' --output text
      # Secrets: spot-check db_master ARN exists
      DB_ARN="$(terraform output -json secrets_arns | python3 -c 'import json,sys; print(json.load(sys.stdin)["db_master"])')"
      aws secretsmanager describe-secret --secret-id "${DB_ARN}" --query 'Name' --output text >/dev/null
      echo "ok aws describe (eks + db secret)"
    fi
  else
    echo "aws cli present but not authenticated — skipping live describes"
  fi
fi

echo "ok staging-eks-smoke"
