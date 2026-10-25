#!/usr/bin/env bash
# E5: activate / reset / status fault injectors against local sim.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi

export PYTHONPATH="${ROOT}/simulation${PYTHONPATH:+:${PYTHONPATH}}"

exec "${PY}" -m faults "$@"
