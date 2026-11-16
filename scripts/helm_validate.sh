#!/usr/bin/env bash
# O2: helm lint + template for local/staging/production-demo values.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART="${ROOT}/deploy/helm/incidentpilot"

if ! command -v helm >/dev/null 2>&1; then
  echo "helm not found on PATH. Install: https://helm.sh/docs/intro/install/" >&2
  exit 127
fi

echo "helm version:"
helm version --short

ENVS=(local staging production-demo)

for env in "${ENVS[@]}"; do
  values="${CHART}/values-${env}.yaml"
  echo "lint (${env})…"
  helm lint "${CHART}" -f "${values}"
  echo "template (${env})…"
  out="$(mktemp)"
  helm template "ip-${env}" "${CHART}" -f "${values}" --namespace incidentpilot-system >"${out}"
  # Sanity: core components present for local/staging (evaluator only when enabled)
  grep -q "kind: Deployment" "${out}"
  grep -q "incidentpilot-api" "${out}"
  grep -q "incidentpilot-web" "${out}"
  if [[ "${env}" != "local" ]]; then
    grep -q "component: evaluator" "${out}" || grep -q "incidentpilot-evaluator\|-evaluator" "${out}"
    # O5: staging/production-demo enable the user vs webhooks Ingress split.
    grep -q "incidentpilot.io/ingress-class: user" "${out}"
    grep -q "incidentpilot.io/ingress-class: webhooks" "${out}"
    grep -q 'path: "/webhooks"\|path: /webhooks' "${out}"
    # Webhooks Ingress block must not carry oauth2-proxy / OIDC auth-url.
    hooks_block="$(awk '/ingress-class: webhooks/,/^---$/' "${out}" || true)"
    if printf '%s\n' "${hooks_block}" | grep -qi 'auth-url'; then
      echo "fail: webhooks ingress has auth-url (OIDC)" >&2
      exit 1
    fi
  fi
  rm -f "${out}"
  echo "ok helm template (${env})"
done

echo "ok helm validate (all envs)"
