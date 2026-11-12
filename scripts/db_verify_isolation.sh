#!/usr/bin/env bash
# Prove GroundTruth isolation + app cannot DDL (A5 / #4).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="${COMPOSE:-docker compose}"
DB_NAME="${POSTGRES_DB:-incidentpilot}"

cd "${ROOT}"

if ! ${COMPOSE} --profile core ps --status running --services 2>/dev/null | grep -qx postgres; then
  echo "postgres is not running. Start it with: make compose-core" >&2
  exit 1
fi

run_as() {
  local user="$1"
  local password="$2"
  shift 2
  ${COMPOSE} --profile core exec -T \
    -e PGPASSWORD="${password}" \
    postgres \
    psql -v ON_ERROR_STOP=1 -U "${user}" -d "${DB_NAME}" "$@"
}

expect_fail() {
  local label="$1"
  shift
  if "$@" >/tmp/ip-db-verify.out 2>/tmp/ip-db-verify.err; then
    echo "FAIL: expected denial for: ${label}" >&2
    cat /tmp/ip-db-verify.err >&2 || true
    exit 1
  fi
  echo "ok denied: ${label}"
}

expect_ok() {
  local label="$1"
  shift
  if ! "$@" >/tmp/ip-db-verify.out 2>/tmp/ip-db-verify.err; then
    echo "FAIL: expected success for: ${label}" >&2
    cat /tmp/ip-db-verify.err >&2 || true
    exit 1
  fi
  echo "ok allowed: ${label}"
}

APP_PW="${IP_APP_PASSWORD:-incidentpilot_app}"
RUNNER_PW="${IP_RUNNER_PASSWORD:-incidentpilot_runner}"
EVAL_PW="${IP_EVALUATOR_PASSWORD:-incidentpilot_evaluator}"
MIG_PW="${MIGRATOR_PASSWORD:-incidentpilot_migrator}"

echo "Verifying DB isolation…"

expect_fail "ip_app SELECT eval.ground_truth" \
  run_as ip_app "${APP_PW}" -c "SELECT 1 FROM eval.ground_truth LIMIT 1"

expect_fail "ip_runner SELECT eval.ground_truth" \
  run_as ip_runner "${RUNNER_PW}" -c "SELECT 1 FROM eval.ground_truth LIMIT 1"

expect_fail "ip_app INSERT eval.ground_truth" \
  run_as ip_app "${APP_PW}" -c "INSERT INTO eval.ground_truth (scenario_key, answer_payload) VALUES ('_deny', '{}'::jsonb)"

expect_fail "ip_runner INSERT eval.ground_truth" \
  run_as ip_runner "${RUNNER_PW}" -c "INSERT INTO eval.ground_truth (scenario_key, answer_payload) VALUES ('_deny', '{}'::jsonb)"

expect_fail "ip_app DDL CREATE TABLE" \
  run_as ip_app "${APP_PW}" -c "CREATE TABLE domain._should_not_exist (id int)"

expect_ok "ip_evaluator SELECT eval.ground_truth" \
  run_as ip_evaluator "${EVAL_PW}" -c "SELECT count(*) FROM eval.ground_truth"

expect_ok "ip_evaluator SELECT structured GT columns" \
  run_as ip_evaluator "${EVAL_PW}" -c "SELECT scenario_key, origin_service_keys, match_spec FROM eval.ground_truth WHERE scenario_key = 'bad_deploy'"

expect_ok "migrator DDL in domain" \
  run_as migrator "${MIG_PW}" -c "CREATE TABLE IF NOT EXISTS domain._migrator_ddl_probe (id int PRIMARY KEY); DROP TABLE domain._migrator_ddl_probe"

echo "db isolation OK"
