# RAG Ops - User Guide

## Overview

RAG Ops is a CLI onboarding copilot for codebases.

The core user flow is:
1. `ragops init`
2. `ragops scan`
3. `ragops chat`

MVP scope and acceptance gates are defined in `docs/mvp.md`.

## Quickstart (Local CLI)

```bash
pip install ragops
cd /path/to/your-project
ragops init
ragops scan
ragops chat
```

Single-turn example:

```bash
ragops chat "How should I start learning this codebase?"
```

## What `ragops scan` Does

`ragops scan` performs one command onboarding:
1. Ingests project files into a collection.
2. Generates onboarding manuals in `./.ragops/manuals` by default.
3. Ingests those manuals so chat can cite them immediately.

Required generated outputs:
- `PROJECT_OVERVIEW.md`
- `ARCHITECTURE_MAP.md`
- `CODEBASE_MANUAL.md`
- `API_MANUAL.md`
- `ARCHITECTURE_DIAGRAM.md`
- `OPERATIONS_RUNBOOK.md`
- `UNKNOWNS_AND_GAPS.md`
- `DATABASE_MANUAL.md`
- `SCAN_INDEX.json`

Full contract and quality rules: `docs/scan-output-spec.md`.

## Core CLI Commands

```bash
# initialize local project config
ragops init

# scan project + generate manuals + ingest manuals
ragops scan

# optional: custom collection name
ragops scan --collection my-project

# interactive multi-turn chat
ragops chat

# single turn chat
ragops chat "How does ingestion work?"

# tune answer style
ragops chat "Explain this code path" \
  --mode explain_like_junior \
  --answer-style concise

# inspect ranking decisions for each citation
ragops chat "why this answer?" --show-ranking-signals

# submit quality feedback
ragops feedback --verdict positive --comment "helpful answer"

# run eval dataset
ragops eval --dataset ./eval/cases.yaml
```

## Config and Profiles

`ragops init` can store reusable defaults in `~/.ragops/config.yaml`.

Useful config commands:

```bash
ragops config show
ragops config set --openai-api-key <key> --storage-backend sqlite --llm-enabled true
ragops config doctor
ragops config doctor --fix
```

## GitHub Repo Workflow (Secondary)

If you want explicit repo registration and sync commands:

```bash
ragops repo add https://github.com/<org>/<repo> --ref main --generate-manuals
ragops repo list
ragops repo sync <owner-repo>
ragops repo sync --all
```

Key flags:
- `repo add --name` to override repo key.
- `repo add --collection` to set base collection name.
- `repo add --github-token` for private repos.
- `repo add --skip-ingest` to register without indexing.
- `repo add --generate-manuals` to generate and ingest manuals collection.
- `repo sync --ref` to sync against branch/tag.
- `repo sync --reset-code-collection` to purge and reindex code collection.
- `repo sync --reset-manuals-collection` to purge and reindex manuals collection.

## API Endpoints

Base URL examples:
- Local: `http://localhost:8000`
- AWS: `https://{api-id}.execute-api.{region}.amazonaws.com/{stage}`

Main endpoints:
- `GET /health`
- `POST /v1/query`
- `POST /v1/chat`
- `POST /v1/feedback`
- `POST /v1/repos/onboard`

Reference: `docs/api-contract.md`.

Note:
- `POST /v1/ingest` with `s3_prefix` is not implemented yet.

## Optional Frontend Flow

```bash
make mock-api
make frontend
```

Then open `http://127.0.0.1:4173`.

Frontend docs:
- `docs/frontend-chat-manual.md`
- `docs/testing-playbook.md`

## Troubleshooting

### No results from chat/query
1. Re-run `ragops scan`.
2. Confirm the expected collection name.
3. Increase retrieval depth with `--top-k`.

### Chat returns citations but weak explanation
1. Ensure `LLM_ENABLED=true`.
2. Ensure valid `OPENAI_API_KEY` is configured.
3. Try `--mode explain_like_junior --answer-style detailed`.

### Config or provider mismatch
1. Run `ragops config doctor`.
2. Confirm provider API key and embedding compatibility with DB schema.

## Related Docs

- `docs/mvp.md`
- `docs/scan-output-spec.md`
- `docs/roadmap.md`
- `docs/runbooks.md`
- `docs/mvp-results.md`
