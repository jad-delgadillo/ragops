# RAG Ops Testing Playbook (Local + Lambda)

This guide explains how to test safely without polluting or rewriting core project artifacts.

## Quick-Start Checklist

### A) Core local test (safe defaults)
```bash
cd /Users/jorgedelgadillo/Developer/ragops
make dev
make install
.venv/bin/python -m services.cli.main ingest --dir ./services --project ragops_core_dev
.venv/bin/python -m services.cli.main ingest --dir ./docs --project ragops_core_dev
.venv/bin/python -m services.cli.main chat "Explain the architecture" --collection ragops_core_dev --mode explain_like_junior
```

### B) Lambda smoke test
```bash
cd /Users/jorgedelgadillo/Developer/ragops
./scripts/package_lambda.sh
cd terraform/envs/dev
set -a; source /Users/jorgedelgadillo/Developer/ragops/.env; set +a
TF_VAR_neon_connection_string="${NEON_CONNECTION_STRING:-$DATABASE_URL}" TF_VAR_openai_api_key="$OPENAI_API_KEY" TF_VAR_llm_enabled=true terraform apply -auto-approve
API_URL="$(terraform output -raw api_url)"
curl -sS "$API_URL/health"
curl -sS -X POST "$API_URL/v1/chat" -H "Content-Type: application/json" -d '{"question":"What is this project about?","collection":"ragops_core_dev","mode":"explain_like_junior","answer_style":"concise","top_k":5}'
```

### C) Normalize old repo collections (one-time)
```bash
cd /Users/jorgedelgadillo/Developer/ragops
.venv/bin/python -m services.cli.main repo migrate-collections --all
.venv/bin/python -m services.cli.main repo migrate-collections --all --apply --purge-old
```

### D) Clean reindex a repo collection (remove stale mixed docs)
```bash
cd /Users/jorgedelgadillo/Developer/ragops
.venv/bin/python -m services.cli.main repo sync <owner-repo> \
  --generate-manuals \
  --reset-code-collection \
  --reset-manuals-collection
```

## 1. Testing Modes

### Mode A: Core project development (this repository)
Goal: test retrieval/chat behavior for `ragops` itself while minimizing file changes.

### Mode B: Product usage testing (external GitHub repos)
Goal: validate repo onboarding workflows (`repo add/sync`) as an end-user flow.

Keep these modes separate.

## 2. Which Commands Write Data?

### Read-only commands
- `query`
- `chat`
- `providers`
- `repo list`
- `curl .../health`
- `curl .../v1/chat` (API call only)

### Write commands (create/update local/DB/infra state)
- `ingest` (writes vectors/docs to DB)
- `generate-manuals` (writes markdown files)
- `repo add` / `repo sync` (clones/pulls repos, updates `.ragops/repos.yaml`, ingests)
- `feedback` (writes feedback table)
- `eval` (writes report files unless output paths are redirected)
- `terraform apply` (changes cloud infra)

## 3. Safe Local Workflow (for Core Development)

Use dedicated test collection names and temp output directories.

```bash
cd /Users/jorgedelgadillo/Developer/ragops
```

### 3.1 Start local dependencies
```bash
make dev
make install
```

### 3.2 Ingest only intended source folders (avoid noisy `.` ingestion)
```bash
.venv/bin/python -m services.cli.main ingest --dir ./services --project ragops_core_dev
.venv/bin/python -m services.cli.main ingest --dir ./docs --project ragops_core_dev
```

### 3.3 Generate manuals to temp path (avoid modifying tracked `manuals/`)
```bash
.venv/bin/python -m services.cli.main generate-manuals --output /tmp/ragops-manuals-core --no-db
```

Optional manual ingestion (separate collection):
```bash
.venv/bin/python -m services.cli.main ingest --dir /tmp/ragops-manuals-core --project ragops_core_dev_manuals
```

### 3.4 Query and chat
```bash
.venv/bin/python -m services.cli.main query "What can I ask you about?" --collection ragops_core_dev
.venv/bin/python -m services.cli.main chat "Explain the architecture" --collection ragops_core_dev --mode explain_like_junior
```

## 4. Safe GitHub Repo Workflow (without polluting core collections)

Use explicit code/manual collections and optional temp clone cache.

```bash
.venv/bin/python -m services.cli.main repo add https://github.com/<org>/<repo> \
  --name <org-repo> \
  --collection <org-repo>_code \
  --generate-manuals \
  --manuals-collection <org-repo>_manuals \
  --cache-dir /tmp/ragops-repos
```

Sync later:
```bash
.venv/bin/python -m services.cli.main repo sync <org-repo>
```

Ask questions:
```bash
# code-focused
.venv/bin/python -m services.cli.main chat "What is the architecture?" --collection <org-repo>_code

# manuals-focused
.venv/bin/python -m services.cli.main chat "Summarize onboarding docs" --collection <org-repo>_manuals
```

## 5. Lambda Testing Workflow

## 5.1 Deploy
```bash
cd /Users/jorgedelgadillo/Developer/ragops
./scripts/package_lambda.sh

cd /Users/jorgedelgadillo/Developer/ragops/terraform/envs/dev
set -a
source /Users/jorgedelgadillo/Developer/ragops/.env
set +a

TF_VAR_neon_connection_string="${NEON_CONNECTION_STRING:-$DATABASE_URL}" \
TF_VAR_openai_api_key="$OPENAI_API_KEY" \
TF_VAR_llm_enabled=true \
terraform apply -auto-approve
```

Fast redeploy when only Lambda code changed (recommended during iteration):
```bash
cd /Users/jorgedelgadillo/Developer/ragops/terraform/envs/dev
terraform apply \
  -replace=aws_s3_object.lambda_package \
  -replace=module.apigw_lambda.aws_api_gateway_deployment.api \
  -auto-approve
```

## 5.2 Smoke test API
```bash
API_URL="$(terraform output -raw api_url)"

curl -sS "$API_URL/health"

curl -sS -X POST "$API_URL/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is this project about?","collection":"ragops_core_dev","mode":"explain_like_junior","answer_style":"concise","top_k":5}'
```

## 5.3 Frontend test against Lambda
```bash
cd /Users/jorgedelgadillo/Developer/ragops
make frontend
```

Open `http://127.0.0.1:4173`, set:
- `API Base URL` = `$(terraform output -raw api_url)`
- `Collection` = your test collection (`ragops_core_dev`, etc.)
- Click `New Session` after major config changes.

## 6. Common Mistakes to Avoid

- Running `make ingest` with broad config (`doc_dirs: [docs, .]`) when you only wanted specific folders.
- Ingesting manuals and code into the same collection (mixes answer quality).
- Reusing old chat session IDs after changing `LLM_ENABLED` or retrieval settings.
- Using `repo add --force` on an existing repo key without intent.
- Generating manuals to tracked folders during experiments instead of `/tmp/...`.

## 7. Recommended Team Convention

- Core repo test collections:
  - `ragops_core_dev`
  - `ragops_core_dev_manuals`
- External repo test collections:
  - `<repo>_code`
  - `<repo>_manuals`
- Always document in PR notes:
  - which collection names were used
  - whether manuals were included
  - whether test was local DB or Lambda
