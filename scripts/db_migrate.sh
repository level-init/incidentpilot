#!/usr/bin/env bash
# Apply deploy/db/migrations/*.sql in order.
#
# Modes:
#   Compose (default): exec into local profile=core postgres.
#   Direct: set MIGRATE_DSN (e.g. CI) to a superuser URL and use host psql.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="${COMPOSE:-docker compose}"
DB_NAME="${POSTGRES_DB:-incidentpilot}"
DB_USER="${POSTGRES_USER:-incidentpilot}"
MIGRATIONS_DIR="${ROOT}/deploy/db/migrations"

cd "${ROOT}"

if [[ -n "${MIGRATE_DSN:-}" ]]; then
  psql_boot() {
    psql -v ON_ERROR_STOP=1 "${MIGRATE_DSN}" "$@"
  }
else
  if ! ${COMPOSE} --profile core ps --status running --services 2>/dev/null | grep -qx postgres; then
    echo "postgres is not running. Start it with: make compose-core" >&2
    echo "(or set MIGRATE_DSN for direct psql, e.g. CI)" >&2
    exit 1
  fi

  psql_boot() {
    ${COMPOSE} --profile core exec -T \
      -e PGPASSWORD="${POSTGRES_PASSWORD:-incidentpilot}" \
      postgres \
      psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${DB_NAME}" "$@"
  }
fi

echo "Ensuring schema_migrations table…"
psql_boot <<'SQL'
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

shopt -s nullglob
files=("${MIGRATIONS_DIR}"/*.sql)
if ((${#files[@]} == 0)); then
  echo "No migrations in ${MIGRATIONS_DIR}" >&2
  exit 1
fi

for file in "${files[@]}"; do
  version="$(basename "${file}" .sql)"
  already="$(
    psql_boot -Atc "SELECT 1 FROM public.schema_migrations WHERE version = '${version}'" \
      | tr -d '[:space:]'
  )"
  if [[ "${already}" == "1" ]]; then
    echo "skip ${version}"
    continue
  fi
  echo "apply ${version}"
  psql_boot -f - <"${file}"
  psql_boot -c "INSERT INTO public.schema_migrations (version) VALUES ('${version}')"
done

echo "migrations OK"
