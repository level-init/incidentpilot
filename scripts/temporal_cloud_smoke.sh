#!/usr/bin/env bash
# O6: smoke subscribe against Temporal Cloud (TLS + API key).
# Falls back with clear guidance when Cloud credentials are absent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ -z "${TEMPORAL_API_KEY:-}" ]]; then
  cat >&2 <<'EOF'
temporal-cloud-smoke: TEMPORAL_API_KEY is unset.

Prefer Temporal Cloud for staging/production-demo (docs/temporal-cloud.md).
Self-host fallback for local / blocked Cloud:

  make compose-core
  make temporal-queue-smoke

To smoke Cloud, export:

  TEMPORAL_ADDRESS='<ns>.<acct>.tmprl.cloud:7233'
  TEMPORAL_NAMESPACE='<ns>.<acct>'
  TEMPORAL_API_KEY='...'
  TEMPORAL_HOSTING=cloud
EOF
  exit 2
fi

export TEMPORAL_HOSTING="${TEMPORAL_HOSTING:-cloud}"
export TEMPORAL_TLS="${TEMPORAL_TLS:-true}"
: "${TEMPORAL_ADDRESS:?set TEMPORAL_ADDRESS to the Cloud gRPC endpoint}"
: "${TEMPORAL_NAMESPACE:?set TEMPORAL_NAMESPACE to the Cloud namespace}"

BIN="${ROOT}/.venv/bin"
if [[ ! -x "${BIN}/python" ]]; then
  echo "Missing .venv — run: make bootstrap" >&2
  exit 1
fi

echo "temporal-cloud-smoke: hosting=${TEMPORAL_HOSTING} address=${TEMPORAL_ADDRESS} namespace=${TEMPORAL_NAMESPACE}"
PYTHONPATH="${ROOT}/worker:${ROOT}/shared:${PYTHONPATH:-}" \
  "${BIN}/python" -m incidentpilot_worker smoke
PYTHONPATH="${ROOT}/worker:${ROOT}/shared:${PYTHONPATH:-}" \
  "${BIN}/python" -m incidentpilot_worker evidence smoke
PYTHONPATH="${ROOT}/remediation_worker:${ROOT}/shared:${PYTHONPATH:-}" \
  "${BIN}/python" -m incidentpilot_remediation smoke
echo "ok temporal-cloud-smoke"
