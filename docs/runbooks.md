# Runbooks

## Local Development

### Zero-dependency CLI (SQLite default)
```bash
ragops init
ragops config doctor
ragops config doctor --fix
ragops scan
ragops chat
```

### Start the stack
```bash
make dev          # starts Postgres + pgvector
make install      # install Python deps
```

### Ingest documents
```bash
make ingest DIR=./docs
```

### One-command scan
```bash
.venv/bin/python -m services.cli.main scan
```

### Query
```bash
make query Q="How does the ingestion work?"
```

### Chat (multi-turn codebase Q and A)
```bash
.venv/bin/python -m services.cli.main chat "How should I learn this codebase?" --mode explain_like_junior
# Continue same thread:
.venv/bin/python -m services.cli.main chat "What file should I read first?" --session-id <session-id>
```

### Feedback loop
```bash
.venv/bin/python -m services.cli.main feedback --verdict positive --comment "Helpful answer"
```

### Evaluation
```bash
.venv/bin/python -m services.cli.main eval --dataset ./eval/cases.yaml
```

### Frontend chat
```bash
make mock-api
make frontend
```
Open `http://127.0.0.1:4173`.
Detailed guide: `docs/frontend-chat-manual.md`

### Generate project manuals
```bash
.venv/bin/python -m services.cli.main generate-manuals --output ./manuals
# Optional: ingest generated manuals
.venv/bin/python -m services.cli.main generate-manuals --output ./manuals --ingest
```

### GitHub repo indexing
```bash
# Register + index GitHub repo
.venv/bin/python -m services.cli.main repo add https://github.com/<org>/<repo> --ref main --generate-manuals

# Refresh tracked repo
.venv/bin/python -m services.cli.main repo sync <owner-repo>

# Refresh all tracked repos
.venv/bin/python -m services.cli.main repo sync --all

# Show tracked repos
.venv/bin/python -m services.cli.main repo list

# Notes:
# - Repo source is ingested into <owner-repo>_code
# - Generated manuals are ingested into <owner-repo>_manuals by default

# For repos created before split collections:
.venv/bin/python -m services.cli.main repo migrate-collections --all
.venv/bin/python -m services.cli.main repo migrate-collections --all --apply --purge-old

# Clean reindex one repo to remove stale mixed chunks
.venv/bin/python -m services.cli.main repo sync <owner-repo> \
  --generate-manuals \
  --reset-code-collection \
  --reset-manuals-collection
```

### Reset database
```bash
make dev-reset    # drops volume and re-creates
```

---

## AWS Deployment

### Prerequisites
- AWS CLI configured
- Terraform >= 1.5

### Deploy infrastructure
```bash
cd terraform/envs/dev
terraform init
terraform plan
terraform apply
```

### Upload documents
```bash
./scripts/upload_docs.sh ./docs ragops-dev-documents docs/
```

### Trigger ingestion
```bash
API_URL=$(terraform output -raw api_url)
curl -X POST ${API_URL}/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"s3_prefix": "docs/", "collection": "default"}'
```

### Query the API
```bash
curl -X POST ${API_URL}/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I deploy?", "collection": "default"}'
```

### Async repo indexing API
```bash
# Start indexing job
curl -sS -X POST ${API_URL}/v1/repos/onboard \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"repo_url":"https://github.com/openai/openai-python","ref":"main","collection":"openai-python","generate_manuals":true,"reset_code_collection":true,"reset_manuals_collection":true,"async":true}'

# Poll status (replace JOB_ID)
curl -sS -X POST ${API_URL}/v1/repos/onboard \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"action":"status","job_id":"JOB_ID"}'
```

---

## Troubleshooting

### Database connection failed
1. Check Docker is running: `docker ps`
2. Check port: `pg_isready -h localhost -p 5432`
3. Check credentials in `.env`

### Embedding errors
1. Verify `OPENAI_API_KEY` is set in `.env`
2. Check API key validity: `curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"`
3. Check rate limits

### Chat stays in retrieval-only mode
1. Set `LLM_ENABLED=true`
2. Confirm provider key (`OPENAI_API_KEY` or selected provider key) is valid

### No results from query
1. Verify documents are ingested: check `indexed_docs` count
2. Check collection name matches
3. Try with `top_k=10` for broader search

### Terraform plan fails
1. Ensure AWS credentials are configured
2. Check VPC and subnet IDs are valid
3. Run `terraform init` if modules changed
