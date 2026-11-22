#!/usr/bin/env bash
# O8: destroy the ephemeral staging stack. Requires confirmation unless FORCE=1.
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

if [[ ! -d "${STAGING}/.terraform" ]]; then
  echo "staging-eks-teardown: ${STAGING} not initialized — nothing to destroy" >&2
  exit 2
fi

cd "${STAGING}"

if [[ ! -f terraform.tfstate ]] && [[ ! -f .terraform/terraform.tfstate ]]; then
  # Remote backends still have state in cloud; allow destroy to proceed.
  echo "note: no local terraform.tfstate (remote backend or empty)"
fi

echo "Planning destroy for staging ephemeral stack…"
terraform plan -destroy -input=false

if [[ "${FORCE:-0}" == "1" ]]; then
  echo "FORCE=1 — destroying without prompt"
elif [[ -t 0 ]]; then
  read -r -p "Destroy staging resources? type 'destroy' to confirm: " ans
  if [[ "${ans}" != "destroy" ]]; then
    echo "aborted"
    exit 1
  fi
else
  echo "non-interactive shell: re-run with FORCE=1 to destroy" >&2
  exit 1
fi

terraform destroy -input=false -auto-approve
echo "ok staging-eks-teardown — confirm AWS console / billing for leftovers"
echo "See docs/staging-eks.md"
