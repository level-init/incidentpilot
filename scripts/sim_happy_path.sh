#!/usr/bin/env bash
# E1: curl happy-path checkout through sim-gateway.
set -euo pipefail

GATEWAY="${SIM_GATEWAY_URL:-http://localhost:8100}"

echo "Checking gateway health at ${GATEWAY}/healthz…"
curl -sf "${GATEWAY}/healthz" >/dev/null
echo "ok healthz"

echo "POST ${GATEWAY}/v1/checkout…"
resp="$(curl -sf -X POST "${GATEWAY}/v1/checkout" \
  -H 'content-type: application/json' \
  -d '{"user_id":"user_demo","token":"tok_demo_user","sku":"SKU-WIDGET","quantity":1,"card_last4":"4242"}')"

echo "${resp}" | grep -q '"status":"confirmed"' || {
  echo "unexpected response: ${resp}" >&2
  exit 1
}
echo "${resp}" | grep -q '"order_id"' || {
  echo "missing order_id: ${resp}" >&2
  exit 1
}

echo "ok sim happy-path checkout"
echo "${resp}"
