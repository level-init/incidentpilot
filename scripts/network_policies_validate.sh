#!/usr/bin/env bash
# O4: render NetworkPolicies via kustomize (no cluster required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${ROOT}/deploy/k8s/networkpolicies"

if command -v kubectl >/dev/null 2>&1; then
  echo "kubectl kustomize…"
  out="$(kubectl kustomize "${DIR}")"
elif command -v kustomize >/dev/null 2>&1; then
  echo "kustomize build…"
  out="$(kustomize build "${DIR}")"
else
  echo "kubectl/kustomize not found — skipping render (pytest still covers YAML)" >&2
  exit 0
fi

echo "${out}" | grep -q "kind: NetworkPolicy"
echo "${out}" | grep -q "default-deny-ingress"
echo "${out}" | grep -q "namespace: incidentpilot-system"
echo "${out}" | grep -q "namespace: incidentpilot-eval"
# Control plane must not name the eval namespace in allow paths.
if echo "${out}" | awk '/namespace: incidentpilot-system/,/^---$/' | grep -q 'incidentpilot-eval'; then
  echo "fail: system policies reference incidentpilot-eval" >&2
  exit 1
fi
count="$(echo "${out}" | grep -c 'kind: NetworkPolicy' || true)"
echo "ok networkpolicies render (NetworkPolicy count=${count})"
