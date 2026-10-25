#!/usr/bin/env bash
# Verify local observability stack health (E3 / #28).
set -euo pipefail

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://localhost:9093}"
LOKI_URL="${LOKI_URL:-http://localhost:3100}"
TEMPO_URL="${TEMPO_URL:-http://localhost:3200}"
GRAFANA_USER="${GRAFANA_ADMIN_USER:-admin}"
GRAFANA_PASS="${GRAFANA_ADMIN_PASSWORD:-admin}"

echo "Checking Alertmanager at ${ALERTMANAGER_URL}…"
curl -sf "${ALERTMANAGER_URL}/-/healthy" >/dev/null
curl -sf "${ALERTMANAGER_URL}/api/v2/status" | grep -q '"cluster"'
echo "ok alertmanager"

echo "Checking Prometheus at ${PROMETHEUS_URL}…"
curl -sf "${PROMETHEUS_URL}/-/healthy" >/dev/null
curl -sf "${PROMETHEUS_URL}/api/v1/targets" | grep -q sim-services
echo "ok prometheus"

echo "Checking Loki at ${LOKI_URL}…"
curl -sf "${LOKI_URL}/ready" >/dev/null
echo "ok loki"

echo "Checking Tempo at ${TEMPO_URL}…"
curl -sf "${TEMPO_URL}/ready" >/dev/null
echo "ok tempo"

echo "Checking Grafana at ${GRAFANA_URL}…"
curl -sf "${GRAFANA_URL}/api/health" | grep -q ok
# Provisioned Simulation traffic dashboard (uid=sim-traffic)
curl -sf -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
  "${GRAFANA_URL}/api/dashboards/uid/sim-traffic" | grep -q '"uid":"sim-traffic"'
echo "ok grafana"

echo "obs stack OK"
