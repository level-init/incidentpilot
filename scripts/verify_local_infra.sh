#!/usr/bin/env bash
# Verify Temporal UI + local S3 put/get (A6 / #5).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="${COMPOSE:-docker compose}"
S3_ENDPOINT="${S3_ENDPOINT:-http://localhost:9000}"
EVIDENCE_BUCKET="${S3_BUCKET_EVIDENCE:-incidentpilot-evidence}"
ACCESS_KEY="${MINIO_ROOT_USER:-minioadmin}"
SECRET_KEY="${MINIO_ROOT_PASSWORD:-minioadmin}"
TEMPORAL_UI="${TEMPORAL_UI_URL:-http://localhost:8088}"

cd "${ROOT}"

echo "Checking Temporal UI at ${TEMPORAL_UI}…"
curl -sf -o /dev/null "${TEMPORAL_UI}/"
echo "ok temporal UI"

echo "Checking Silo health…"
curl -sf -o /dev/null "${S3_ENDPOINT}/minio/health/live"
echo "ok silo health"

KEY="_health/incidentpilot-$(date -u +%Y%m%dT%H%M%SZ).txt"
PAYLOAD="incidentpilot-health-ok"

echo "S3 put/get against s3://${EVIDENCE_BUCKET}/${KEY}…"
${COMPOSE} --profile core run --rm --no-deps \
  -e AWS_ACCESS_KEY_ID="${ACCESS_KEY}" \
  -e AWS_SECRET_ACCESS_KEY="${SECRET_KEY}" \
  -e AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" \
  --entrypoint /bin/sh \
  minio-init \
  -c "
    set -eu
    printf '%s' '${PAYLOAD}' | aws --endpoint-url http://minio:9000 s3 cp - s3://${EVIDENCE_BUCKET}/${KEY}
    got=\$(aws --endpoint-url http://minio:9000 s3 cp s3://${EVIDENCE_BUCKET}/${KEY} -)
    test \"\$got\" = '${PAYLOAD}'
    aws --endpoint-url http://minio:9000 s3 rm s3://${EVIDENCE_BUCKET}/${KEY} >/dev/null
  "

echo "ok s3 put/get"
echo "local infra OK"
