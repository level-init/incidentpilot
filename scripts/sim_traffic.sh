#!/usr/bin/env bash
# E4: run baseline traffic (+ health/ready gate) against local sim stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

DURATION="${DURATION:-60}"
RPS="${RPS:-1}"
MAX_ERROR_RATE="${MAX_ERROR_RATE:-0.05}"

if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi

export PYTHONPATH="${ROOT}/simulation${PYTHONPATH:+:${PYTHONPATH}}"

exec "${PY}" -m traffic \
  --duration "${DURATION}" \
  --rps "${RPS}" \
  --max-error-rate "${MAX_ERROR_RATE}" \
  "$@"
