# RAG Ops Platform — Blueprint v2 (Aurora Serverless v2 + OpenAI embeddings, Bedrock-ready)

## 0) TL;DR Decisions
- **Cloud:** AWS (single-cloud for speed + employability)
- **DB:** **Aurora Serverless v2 (Postgres) + pgvector**
- **Compute:** **API Gateway + Lambda (Python)**
- **Embeddings (MVP):** **OpenAI `text-embedding-3-small`**
- **Enterprise option (v2):** **AWS Bedrock** (Titan Embeddings + Bedrock text model)
- **Frontend:** **Not required for MVP** (API + CLI demo is enough). Add UI only if it helps a recruiter see value fast.

---

## 1) Purpose
Build a production-style **RAG infrastructure** that proves you can deploy and operate AI-enabled systems:
- IaC with Terraform
- Serverless compute
- Vector DB (pgvector)
- Observability + security
- Cost-aware design (pay-for-use as much as possible)

---

## 2) Why No Frontend (Now)
### Why we skip it in MVP
- The job signal is **DevOps**: IaC, AWS, pipelines, observability, security.
- A frontend burns time and doesn’t increase DevOps credibility as much.
- Recruiters can validate the project with:
  - `curl` requests
  - a small CLI
  - Terraform deploy instructions

### When a frontend becomes worth it
Add a minimal **Next.js + shadcn** UI if:
- You want a **1-minute wow demo** (paste question, see citations)
- You plan to share it widely (LinkedIn, GitHub README video)
- You need a cleaner showcase for non-technical reviewers

**Rule:** ship MVP with API + CLI first. UI is optional v1.1.

---

## 3) Architecture
### AWS Components
- **API Gateway** → **Lambda Query API** (Python)
- **Aurora Serverless v2 (Postgres)** with **pgvector**
- **S3**: document storage
- **CloudWatch**: logs, metrics
- **Secrets Manager / SSM**: credentials
- (Optional hardening) **RDS Proxy** if Lambda concurrency creates DB connection pressure

### Data Flow
1) Upload docs to S3
2) Ingest job reads docs, chunks, embeds, upserts vectors into Aurora
3) Query API embeds question, retrieves top-K, generates answer + citations

---

## 4) Core Features (MVP)
### A) Ingestion
- Input: S3 prefix (e.g., `s3://bucket/docs/`)
- Steps:
  1) download
  2) normalize text
  3) chunk
  4) embed
  5) upsert into pgvector
- Outputs:
  - indexed documents count
  - chunk count
  - timing stats

### B) Query
- Input: `question`, `collection`
- Steps:
  1) embed question
  2) vector search top-K
  3) assemble context with citations
  4) generate response
- Output includes citations: file + line range (or chunk IDs)

### C) Health
- DB connectivity
- embedding provider connectivity
- version + config summary (no secrets)

---

## 5) Provider Strategy (OpenAI now, Bedrock later)
### Provider-agnostic interfaces (required)
Implement two interfaces so switching providers is trivial:

**EmbeddingProvider**
- `embed(texts: list[str]) -> list[list[float]]`

**LLMProvider**
- `generate(prompt: str, *, max_tokens: int, temperature: float) -> str`

### MVP Provider
- OpenAI embeddings: `text-embedding-3-small`
- (LLM optional for MVP; retrieval-only mode allowed for debugging)

### Enterprise Provider (v2)
- Bedrock Titan Embeddings v2
- Bedrock text model (configurable)

---

## 6) Repo Structure
```
rag-ops-platform/
  README.md
  docs/
    architecture.md
    runbooks.md
    threat-model.md
    cost-notes.md
    api-contract.md
  services/
    api/
      app/
      tests/
    ingest/
      app/
      tests/
  terraform/
    modules/
      apigw_lambda/
      aurora_serverless/
      s3/
      iam/
    envs/
      dev/
  scripts/
    upload_docs.sh
    local_dev.sh
  .github/workflows/
    ci.yml
    terraform.yml
```

---

## 7) API Contract (MVP)
### `POST /v1/ingest`
```json
{ "s3_prefix": "docs/", "collection": "default" }
```
Response:
```json
{ "status": "ok", "indexed_docs": 12, "chunks": 842 }
```

### `POST /v1/query`
```json
{ "question": "How do I deploy this?", "collection": "default" }
```
Response:
```json
{
  "answer": "...",
  "citations": [
    { "source": "docs/runbooks.md", "line_start": 40, "line_end": 88 }
  ],
  "latency_ms": 512,
  "retrieved": 6
}
```

### `GET /health`
```json
{ "status": "ok", "db": "ok", "embed": "ok" }
```

---

## 8) Database (Aurora Postgres + pgvector)
### Tables
- `documents(id, s3_key, sha256, created_at, metadata jsonb)`
- `chunks(id, document_id, chunk_index, content, embedding vector(N), token_count, source_file, line_start, line_end)`

### Indexes
- vector index on `chunks.embedding`
- btree on `documents.sha256` and `chunks.document_id`

### Cost / Performance Notes
- Use caching by `sha256` to avoid re-embedding unchanged docs
- Batch embedding calls

---

## 9) Cost-Control Strategy
- Aurora Serverless v2: scale down when idle (set min ACUs low)
- Cache embeddings by SHA256
- Add `--dry-run` and retrieval-only mode to test without LLM calls
- Limit context size and `max_tokens`

---

## 10) Security Requirements
- No secrets in repo
- Secrets in SSM/Secrets Manager
- IAM least privilege:
  - query lambda: db connect + read secret
  - ingest: s3 read + db connect + read secret
- Input limits + validation
- Optional: redact sensitive patterns (AWS keys) during ingest

---

## 11) Observability Requirements
- Structured JSON logs
- CloudWatch metrics:
  - `QueryLatencyMs`
  - `RetrievedChunks`
  - `EmbeddingLatencyMs`
  - `LLMErrors`
  - `IngestDocsIndexed`
- Optional alarms on error spikes

---

## 12) CI/CD (GitHub Actions)
### `ci.yml`
- lint + unit tests
- type checks (optional)

### `terraform.yml`
- fmt, validate
- plan on PR
- apply via workflow dispatch (manual)

---

## 13) Delivery Plan (30 Days)
### Week 1 — Local engine (no AWS yet)
- Postgres + pgvector locally
- schema + chunking + embedding + retrieval
- return top chunks + citations

### Week 2 — AWS infra + query API
- Terraform Aurora Serverless v2 + S3 + Lambda + API Gateway
- deploy query API connected to Aurora
- CloudWatch logs

### Week 3 — Ingestion end-to-end
- ingest from S3 prefix
- caching by sha256
- CI pipelines
- docs + runbooks

### Week 4 — Hardening + v1 release
- metrics + alarms
- optional RDS Proxy if needed
- cost notes + demo script
- release v1.0 + demo video

---

## 14) How Others Can Try It
### Option A (Best for recruiters): Cloud demo
- Run `terraform apply`
- Upload sample docs to S3
- `curl /v1/ingest` then `curl /v1/query`

### Option B (Best for OSS users): Local Docker
- `docker compose up` (local Postgres+pgvector)
- `make ingest` + `make query`

---

## 15) CV Bullet (ready)
Built a Terraform-managed AWS RAG platform using Python (Lambda + API Gateway), Aurora Serverless v2 Postgres (pgvector), and S3, with ingestion pipelines, cited retrieval, CI/CD automation, cost controls, observability, and least-privilege security; designed pluggable providers for OpenAI and AWS Bedrock.

---

## 16) Immediate Next Steps (Today)
1) Create repo with skeleton
2) Local Postgres+pgvector + schema
3) Implement retrieval-only mode (no LLM)
4) Add OpenAI embeddings provider

Ship the core first. Everything else builds on it.

