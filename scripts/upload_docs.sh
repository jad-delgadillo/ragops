#!/usr/bin/env bash
# Upload documents to S3 for ingestion
# Usage: ./scripts/upload_docs.sh <local-dir> [s3-bucket] [prefix]

set -euo pipefail

LOCAL_DIR="${1:?Usage: upload_docs.sh <local-dir> [s3-bucket] [prefix]}"
BUCKET="${2:-ragops-dev-documents}"
PREFIX="${3:-docs/}"

echo "📤 Uploading documents from ${LOCAL_DIR} to s3://${BUCKET}/${PREFIX}"
aws s3 sync "${LOCAL_DIR}" "s3://${BUCKET}/${PREFIX}" \
    --exclude ".*" \
    --exclude "__pycache__/*" \
    --include "*.md" \
    --include "*.txt" \
    --include "*.py" \
    --include "*.json" \
    --include "*.yaml" \
    --include "*.yml"

echo "✅ Upload complete"
echo "Run the ingest API:"
echo "  curl -X POST \${API_URL}/v1/ingest -d '{\"s3_prefix\": \"${PREFIX}\", \"collection\": \"default\"}'"
