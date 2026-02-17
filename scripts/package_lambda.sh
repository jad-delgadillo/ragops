#!/bin/bash
set -e

# Ensure build dir
mkdir -p build/package
rm -rf build/package/*

# Install deps and copy code using Docker (ensures Linux ARM64 binaries for Lambda)
echo "📦 Packaging Lambda (Linux ARM64)..."
echo "   NOTE: Using Python 3.12 Docker image to build dependencies"

docker run --rm --platform linux/arm64 \
  -v "$PWD":/workspace \
  -w /workspace \
  python:3.12-slim \
  bash -c "apt-get update && apt-get install -y zip && pip install -r scripts/requirements-lambda.txt -t build/package && cp -r services build/package/services"

# Zip it
echo "🤐 Zipping payload..."
cd build/package
# Zip recursively, exclude junk
zip -q -r ../lambda.zip . -x "*.pyc" "__pycache__" "*/__pycache__/*"
cd ../..

echo "✅ Created build/lambda.zip"
