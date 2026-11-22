#!/usr/bin/env bash
# P8: end-to-end scored bad-deployment demo (Level-2 harness + dual-stage eval).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ ! -x .venv/bin/python ]]; then
  echo "missing .venv — run: make bootstrap" >&2
  exit 127
fi

echo "==> P8 demo: bad-deployment scored path"
echo "    docs: docs/demo-guide.md"

echo "==> compose-core (Postgres / Temporal / S3)"
make compose-core
sleep 2

echo "==> migrate"
make migrate

if [[ "${SKIP_ISOLATION:-0}" != "1" ]]; then
  echo "==> test-isolation (required before scored runs)"
  make test-isolation
else
  echo "==> SKIP_ISOLATION=1 — skipping isolation suite"
fi

echo "==> scenario NAME=bad-deployment"
make scenario NAME=bad-deployment

echo "==> eval (dual-stage pins for last scored run)"
make eval

cat <<'EOF'

ok demo-bad-deploy

Next (optional for talk / Q4 recording):
  make api-run          # :8000
  make web-dev          # :3000 — Bearer local-dev or local-dev-evaluator
  Other scenarios: docs/scenarios.md
  Shorter alert-only path: docs/quickstart.md

EOF
