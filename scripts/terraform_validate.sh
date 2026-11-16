#!/usr/bin/env bash
# O1: terraform fmt + validate for staging root (no AWS apply).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING="${ROOT}/deploy/terraform/environments/staging"

if ! command -v terraform >/dev/null 2>&1; then
  echo "terraform not found on PATH (need >= 1.5). Install from https://developer.hashicorp.com/terraform/install" >&2
  exit 127
fi

echo "terraform version:"
terraform version

echo "fmt -check (recursive)…"
terraform fmt -check -recursive "${ROOT}/deploy/terraform"

echo "init -backend=false…"
cd "${STAGING}"
terraform init -backend=false -input=false

echo "validate…"
terraform validate

echo "ok terraform validate (staging)"
