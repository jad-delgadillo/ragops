# RAG Ops Platform - User Guide

## Overview
RAG Ops ingests project docs/code into pgvector and answers questions with retrieval and optional LLM generation.

## Local Setup
```bash
cp .env.example .env
make dev
make install
make init
```

## Core CLI Workflow
```bash
# Index current project (or pass DIR=./docs)
make ingest

# Ask a question
make query Q="How does ingestion work?"

# Multi-turn onboarding chat
python -m services.cli.main chat "How should I learn this codebase?" \
  --mode explain_like_junior \
  --answer-style concise \
  --show-context

# Submit quality feedback
python -m services.cli.main feedback --verdict positive --comment "Helpful answer"

# Generate markdown docs from source structure
python -m services.cli.main generate-docs --output ./docs

# Generate deterministic onboarding manuals (codebase, API, DB)
python -m services.cli.main generate-manuals --output ./manuals

# Optional: ingest the manuals so they are answerable via query
python -m services.cli.main generate-manuals --output ./manuals --ingest

# Run dataset evaluation (JSON or YAML dataset)
python -m services.cli.main eval --dataset ./eval/cases.yaml
```

## GitHub Repo Workflow
Connect a GitHub repository, index it, and chat over its codebase.

```bash
# Add repository (clones into ./.ragops/repos/<owner-repo>, then ingests)
python -m services.cli.main repo add https://github.com/<org>/<repo> \
  --ref main \
  --generate-manuals

# List tracked repositories
python -m services.cli.main repo list

# Sync one tracked repository (git pull + refresh index)
python -m services.cli.main repo sync <owner-repo>

# Sync all tracked repositories
python -m services.cli.main repo sync --all

# Query/chat using the repo collection
python -m services.cli.main chat "What is this repo about?" --collection <owner-repo>
```

Important flags:
- `repo add --name`: override default repo key (`owner-repo`)
- `repo add --collection`: override default collection
- `repo add --github-token`: auth for private repos (or set `GITHUB_TOKEN`)
- `repo add --skip-ingest`: clone/register without indexing
- `repo add --generate-manuals`: generate manual pack under `./manuals/<repo-key>`
- `repo sync --ref`: sync against a specific branch/tag

## Frontend Onboarding Chat
Use the browser UI manual for step-by-step setup:
- `docs/frontend-chat-manual.md`

Quick start:
```bash
make mock-api
make frontend
```
Then open `http://127.0.0.1:4173`.

## Optional Access Control
Enable collection-scoped API key auth:
```env
API_AUTH_ENABLED=true
API_KEYS_JSON={"my-key":{"name":"onboarding-bot","permissions":["query","chat","feedback"],"collections":["default","ragops"]}}
```
When enabled, send `X-API-Key` for protected endpoints.

## API Endpoints
Base URL examples:
- Local: `http://localhost:8000` (if you run an API host)
- AWS: `https://{api-id}.execute-api.{region}.amazonaws.com/{stage}`

### `GET /`
Returns basic service info and endpoint list.

### `GET /health`
Checks DB connectivity and embedding provider/schema compatibility.

### `POST /v1/query`
Ask a grounded question.

Request:
```json
{
  "question": "How do I deploy this project?",
  "collection": "default"
}
```

### `POST /v1/chat`
Multi-turn chat with persistent `session_id`.

Request:
```json
{
  "question": "How should I navigate this codebase?",
  "collection": "default",
  "session_id": "optional-existing-session",
  "mode": "explain_like_junior",
  "answer_style": "concise",
  "top_k": 5
}
```

### `POST /v1/ingest`
Ingest files from a local directory path visible to the runtime.

Request:
```json
{
  "local_dir": "./docs",
  "collection": "default"
}
```

Note: `s3_prefix` mode is not implemented yet in `services/ingest/app/handler.py`.

## Troubleshooting
### No results from query
1. Re-run ingestion for the right collection.
2. Confirm collection names match.
3. Increase retrieval depth (`--top-k`).

### Embedding configuration error
1. Confirm API key for the selected embedding provider is set.
2. Confirm provider embedding dimension matches DB schema.

### Chat returns only source list (no generated explanation)
1. Ensure Lambda/local env has `LLM_ENABLED=true`.
2. Ensure valid `OPENAI_API_KEY` (or selected LLM provider key) is set.
