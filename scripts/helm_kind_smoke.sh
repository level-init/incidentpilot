#!/usr/bin/env bash
# O7: install the Helm chart into kind/k3d and assert core objects exist.
# Does not wait for image pulls / Ready — GHCR digests are out of scope for every PR.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART="${ROOT}/deploy/helm/incidentpilot"
VALUES="${HELM_VALUES:-${CHART}/values-local.yaml}"
RELEASE="${HELM_RELEASE:-ip-o7}"
NS="${HELM_NAMESPACE:-incidentpilot-system}"
EVAL_NS="${HELM_EVAL_NAMESPACE:-incidentpilot-eval}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required tool: $1" >&2
    exit 127
  }
}

need kubectl
need helm

echo "kubectl context: $(kubectl config current-context)"
kubectl cluster-info >/dev/null
helm version --short

echo "helm upgrade --install ${RELEASE} (values=$(basename "${VALUES}"))…"
helm upgrade --install "${RELEASE}" "${CHART}" \
  --namespace "${NS}" \
  --create-namespace \
  -f "${VALUES}" \
  --wait=false \
  --timeout 2m

echo "assert namespaces…"
kubectl get namespace "${NS}"
kubectl get namespace "${EVAL_NS}"

echo "assert control-plane Deployments…"
for component in api worker evidence remediation web; do
  if ! kubectl -n "${NS}" get deploy \
    -l "app.kubernetes.io/component=${component}" \
    -o name | grep -q .; then
    echo "fail: missing Deployment for component=${component}" >&2
    kubectl -n "${NS}" get deploy,svc,sa || true
    exit 1
  fi
done

echo "assert Services…"
kubectl -n "${NS}" get svc incidentpilot-api
kubectl -n "${NS}" get svc incidentpilot-web

echo "assert ServiceAccounts (privilege classes)…"
for sa in \
  incidentpilot-api \
  incidentpilot-worker \
  incidentpilot-evidence \
  incidentpilot-remediation \
  incidentpilot-web; do
  kubectl -n "${NS}" get sa "${sa}" >/dev/null
done
kubectl -n "${EVAL_NS}" get sa incidentpilot-evaluator >/dev/null
kubectl -n "${EVAL_NS}" get sa incidentpilot-runner >/dev/null

echo "assert privilege-class labels on pod templates…"
kubectl -n "${NS}" get deploy -o json | grep -q 'incidentpilot.io/privilege-class'

echo "helm status…"
helm status "${RELEASE}" --namespace "${NS}"

if [[ "${HELM_KIND_CLEANUP:-0}" == "1" ]]; then
  echo "cleanup: helm uninstall ${RELEASE}…"
  helm uninstall "${RELEASE}" --namespace "${NS}" || true
fi

echo "ok helm-kind-smoke (release=${RELEASE})"
