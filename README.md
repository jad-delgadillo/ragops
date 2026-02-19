# RAG Ops

Citation-grounded GitHub repo onboarding copilot.

RAG Ops turns a repository URL into an indexed knowledge base, then answers onboarding questions with file/line citations, session memory, and feedback capture.

## MVP Focus

This repository is now optimized around one product story:

1. Onboard a GitHub repository.
2. Ingest code and generated manuals into isolated collections.
3. Ask onboarding questions in chat mode with citations.
4. Capture feedback and evaluate retrieval quality.

Detailed scope and acceptance criteria: `docs/mvp.md`.

## What Works Today

- Repo onboarding pipeline (download archive, ingest code, optional manual generation).
- Conversational RAG chat with session memory and answer modes.
- Citation payloads for source transparency.
- Feedback endpoint and table for quality loops.
- Local-first development with Docker + PostgreSQL/pgvector.
- AWS deploy path with Lambda + API Gateway + Terraform.

## Known MVP Boundaries

- `POST /v1/ingest` with `s3_prefix` is not implemented yet (returns `501`).
- Bedrock provider classes are present but intentionally stubbed.
- The stable MVP path is OpenAI embeddings + OpenAI LLM.

## Quick Start (Local MVP Flow)

1. Configure environment:
```bash
cp .env.example .env
# Set OPENAI_API_KEY and LLM_ENABLED=true
```

2. Start dependencies and install:
```bash
make dev
make install
```

3. Add and index a GitHub repository:
```bash
.venv/bin/python -m services.cli.main repo add https://github.com/<org>/<repo> \
  --ref main \
  --generate-manuals
```

4. Chat against the indexed code collection:
```bash
.venv/bin/python -m services.cli.main chat \
  "How should I start learning this codebase?" \
  --collection <owner-repo>_code \
  --mode explain_like_junior \
  --answer-style concise
```

5. Submit quality feedback:
```bash
.venv/bin/python -m services.cli.main feedback \
  --verdict positive \
  --collection <owner-repo>_code \
  --comment "Clear answer and useful citations"
```

6. Run eval dataset:
```bash
.venv/bin/python -m services.cli.main eval --dataset ./eval/cases.yaml
```

Optional UI flow:
```bash
make mock-api
make frontend
```
Open `http://127.0.0.1:4173`.

## MVP API Surface

- `GET /health`
- `POST /v1/chat`
- `POST /v1/feedback`
- `POST /v1/repos/onboard` (async supported)
- `POST /v1/query` (non-conversational retrieval/generation)

Reference: `docs/api-contract.md`.

## Architecture

- Runtime: Python 3.11 services.
- Vector DB: PostgreSQL 16 + `pgvector`.
- Local dev: Docker Compose.
- Cloud deploy: AWS Lambda + API Gateway + Terraform.

## Project Structure

```text
.
├── services/
│   ├── api/
│   ├── ingest/
│   ├── core/
│   └── cli/
├── docs/
├── frontend/
├── eval/
└── terraform/
```

## Testing

Run all service tests:
```bash
.venv/bin/python -m pytest services/ -q
```

## License

MIT
