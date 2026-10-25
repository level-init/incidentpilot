#!/usr/bin/env bash
# E4: scenario-runner baseline gate — all /healthz + gateway /readyz.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi

export PYTHONPATH="${ROOT}/simulation${PYTHONPATH:+:${PYTHONPATH}}"

exec "${PY}" -m traffic --health-only
