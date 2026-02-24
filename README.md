# RAG Ops

RAG Ops is a CLI codebase copilot.

It indexes a project, generates project manuals, and answers questions with citations.

## MVP in One Flow

```bash
ragops init
ragops scan
ragops chat
```

That is the product MVP.

## Quickstart (Local CLI)

```bash
pip install ragops
cd /path/to/any-project
ragops init
ragops scan
ragops chat
```

Single-turn usage also works:

```bash
ragops chat "How should I start learning this codebase?"
```

## Quickstart (Docker CLI)

```bash
docker build -t ragops .

# Scan current project (path positional supported)
docker run --rm -it \
  -v "$PWD:/workspace" \
  -w /workspace \
  --env-file .env \
  ragops scan .

# One-shot chat in the same mounted project
docker run --rm \
  -v "$PWD:/workspace" \
  -w /workspace \
  --env-file .env \
  ragops chat "How should I start learning this codebase?"

# Interactive chat shell
docker run --rm -it \
  -v "$PWD:/workspace" \
  -w /workspace \
  --env-file .env \
  ragops chat
```

## What `scan` Produces

`ragops scan` indexes the repository and writes manuals to `./.ragops/manuals` by default.

Current manual outputs:
- `PROJECT_OVERVIEW.md`
- `ARCHITECTURE_MAP.md`
- `CODEBASE_MANUAL.md`
- `API_MANUAL.md`
- `ARCHITECTURE_DIAGRAM.md`
- `OPERATIONS_RUNBOOK.md`
- `UNKNOWNS_AND_GAPS.md`
- `DATABASE_MANUAL.md` (database introspection is skipped in `scan` mode)
- `SCAN_INDEX.json`

After generation, scan ingests these manuals so chat can use them as context.

Detailed contract: `docs/scan-output-spec.md`.

## MVP Scope

In scope:
- Local-first CLI workflow (`init`, `scan`, `chat`)
- Citation-grounded answers with session continuity
- Deterministic manual generation during scan
- Feedback and eval commands for quality tracking

Out of scope for the current MVP:
- Production-ready Bedrock path
- `s3_prefix` ingestion in `/v1/ingest` (currently returns `501`)
- Billing, multi-tenant org management, enterprise auth stack

Full definition: `docs/mvp.md`.

## Core Commands

```bash
ragops init
ragops scan --collection <name>
ragops chat
ragops chat "question" --mode explain_like_junior --answer-style concise
ragops chat "question" --show-ranking-signals
ragops chat "question" --hide-ranking-signals
ragops feedback --verdict positive --comment "helpful answer"
ragops eval --dataset ./eval/cases.yaml
```

Global profile helpers:

```bash
ragops config show
ragops config set --openai-api-key <key> --storage-backend sqlite --llm-enabled true
ragops config set --show-ranking-signals true
ragops config doctor
```

Embedding model migration helper (dimension changes are destructive by design):

```bash
ragops migrate-embedding-dimension --dimension 768 --yes
```

## Optional Repo Workflow

For GitHub repo indexing flows:

```bash
ragops repo add https://github.com/<org>/<repo> --ref main --generate-manuals
ragops repo sync <owner-repo>
ragops repo list
```

## Documentation Map

- MVP definition: `docs/mvp.md`
- Scan output contract: `docs/scan-output-spec.md`
- Product roadmap: `docs/roadmap.md`
- API contract: `docs/api-contract.md`
- User guide: `docs/user-guide.md`
- Runbooks: `docs/runbooks.md`
- MVP results: `docs/mvp-results.md`

## Development

Editable install:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
.venv/bin/python -m pytest services/ -q
```

## License

MIT
