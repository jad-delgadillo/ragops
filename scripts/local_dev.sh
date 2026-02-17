#!/usr/bin/env bash
# Local development setup script
# Usage: ./scripts/local_dev.sh

set -euo pipefail

echo "🚀 RAG Ops Platform — Local Development Setup"
echo "================================================"

# 1. Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "❌ Docker required"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "❌ Python 3.11+ required"; exit 1; }

# 2. Start database
echo "📦 Starting Postgres + pgvector..."
docker compose up -d

echo "⏳ Waiting for database health check..."
for i in {1..30}; do
    if docker compose exec -T postgres pg_isready -U ragops -d ragops >/dev/null 2>&1; then
        echo "✅ Database ready"
        break
    fi
    sleep 1
done

# 3. Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install -e ".[dev]" --quiet

# 4. Create .env if missing
if [ ! -f .env ]; then
    cat > .env <<EOF
# RAG Ops Platform — Local Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ragops
DB_USER=ragops
DB_PASSWORD=ragops
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=your-key-here
LLM_ENABLED=false
LOG_LEVEL=INFO
ENVIRONMENT=local
EOF
    echo "📝 Created .env file — update OPENAI_API_KEY before ingesting"
else
    echo "✅ .env file already exists"
fi

echo ""
echo "================================================"
echo "✅ Setup complete! Next steps:"
echo ""
echo "  1. Set your OpenAI API key in .env"
echo "  2. Ingest documents:  make ingest DIR=./docs"
echo "  3. Query:             make query Q='How do I deploy?'"
echo "  4. Run tests:         make test"
echo "================================================"
