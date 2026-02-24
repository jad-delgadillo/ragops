# Local Testing Guide

How to run the full RAG Ops stack locally for development and testing.

## Prerequisites

- Python 3.11+
- Docker (for Postgres + pgvector)
- OpenAI API key in `.env`

## Quick Start

```bash
# 1. Start the database
make dev

# 2. Install dependencies
make install

# 3. Index a repo (uses OpenAI embeddings, ~$0.10 for small repos)
make repo-add URL=https://github.com/your-org/your-repo

# 4. Start the real API server (Terminal 1)
make local-api

# 5. Start the frontend (Terminal 2)
make frontend

# 6. Open http://localhost:4173 in your browser
```

## Docker CLI (No Local Python Needed)

```bash
# Build the image once
make docker-build

# Scan the current project from inside container
make docker-scan

# Chat against the same mounted project
make docker-chat
```

## Available Servers

| Command | Port | Purpose |
| --- | --- | --- |
| `make local-api` | 8090 | **Real API** — uses your DB + OpenAI key, returns real RAG answers |
| `make mock-api` | 8090 | **Mock API** — canned responses, no API key needed, for UI testing only |
| `make frontend` | 4173 | Frontend chat UI |

> **Important:** `local-api` and `mock-api` share port 8090. Only run one at a time.

## Indexing a Repository

```bash
# First time
make repo-add URL=https://github.com/org/repo

# Re-index (overwrite existing)
make repo-add URL=https://github.com/org/repo FORCE=1

# List tracked repos
make repo-list

# Sync an existing repo (pull latest + re-index)
make repo-sync NAME=org-repo
```

**What happens during indexing:**
1. Clones the repo to `.ragops/repos/<name>/`
2. Reads and chunks all code files
3. Sends chunks to OpenAI for embedding (~$0.10 for small repos)
4. Stores embeddings in local Postgres (pgvector)
5. Registers the repo in `.ragops/repos.yaml`

The collection name will be `<owner>-<repo>_code` (e.g., `jad-delgadillo-ragops_code`).

## Using the Frontend

1. Open `http://localhost:4173`
2. Set **API Base URL** to `http://localhost:8090`
3. Set **Collection** to your repo's collection name (e.g., `jad-delgadillo-ragops_code`)
4. Ask questions in the chat — you'll get real answers with file citations
5. Use 👍/👎 feedback buttons to rate answer quality

### Frontend Modes

| Mode | Best for |
| --- | --- |
| `default` | General questions |
| `explain_like_junior` | Beginner-friendly explanations |
| `show_where_in_code` | Finding specific code locations |
| `step_by_step` | Understanding workflows |

## Running Tests

```bash
# Unit tests (no API key needed)
make test

# With coverage
make test-cov

# Linting
make lint
```

## Troubleshooting

**"Address already in use" on port 8090:**
```bash
lsof -ti :8090 | xargs kill -9
```

**"Repository already exists":**
```bash
make repo-add URL=... FORCE=1
```

**Slow indexing:**
Large repos take time because every file is embedded via OpenAI. For faster testing, use a small repo (< 50 files).

**"make frontend" fails:**
Make sure you're in the project root (`/path/to/ragops`), not a subdirectory.
