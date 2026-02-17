#!/bin/bash
set -e

# Check tools
command -v terraform >/dev/null 2>&1 || { echo >&2 "❌ Terraform not found. Please install."; exit 1; }
command -v aws >/dev/null 2>&1 || { echo >&2 "❌ AWS CLI not found."; exit 1; }
command -v docker >/dev/null 2>&1 || { echo >&2 "❌ Docker not found."; exit 1; }

# Load env vars
if [ -f .env ]; then
  set -a
  source .env
  set +a
else
  echo "⚠️ .env file not found. Ensure keys are set in environment."
fi

# Ensure connection string is present
if [ -z "$NEON_CONNECTION_STRING" ]; then
  echo "❌ NEON_CONNECTION_STRING is missing in .env or environment."
  exit 1
fi

export TF_VAR_neon_connection_string="$NEON_CONNECTION_STRING"
export TF_VAR_openai_api_key="$OPENAI_API_KEY"
export TF_VAR_gemini_api_key="$GEMINI_API_KEY"
export TF_VAR_anthropic_api_key="$ANTHROPIC_API_KEY"
export TF_VAR_groq_api_key="$GROQ_API_KEY"

# Package code
./scripts/package_lambda.sh

# Deploy
echo "🚀 Deploying with Terraform..."
cd terraform/envs/dev
terraform init
terraform apply -auto-approve

echo "✅ Deployment Complete!"
echo "API URL: $(terraform output -raw api_url)"
