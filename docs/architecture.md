# Architecture

## Overview

The RAG Ops Platform is a serverless RAG system built on AWS. It ingests documents, chunks and embeds them into pgvector, and serves retrieval + generation queries via a REST API.

## Data Flow

```
                           ┌─────────────────────┐
                           │   S3 (Documents)    │
                           └──────────┬──────────┘
                                      │ 1. Upload docs
                                      ▼
┌──────────────┐     ┌──────────────────────────────┐
│  API Gateway │────▶│     Ingest Lambda (Python)    │
│ POST /ingest │     │  download → chunk → embed →   │
└──────────────┘     │  upsert into pgvector         │
                     └──────────────┬───────────────┘
                                    │ 2. Store embeddings
                                    ▼
                     ┌─────────────────────────────┐
                     │  Aurora Serverless v2        │
                     │  (Postgres 16 + pgvector)    │
                     │  ┌─────────┐ ┌────────────┐ │
                     │  │documents│ │   chunks    │ │
                     │  └─────────┘ └────────────┘ │
                     └──────────────┬──────────────┘
                                    │ 3. Vector search
                                    ▼
┌──────────────┐     ┌──────────────────────────────┐
│  API Gateway │────▶│     Query Lambda (Python)     │
│ POST /query  │     │  embed question → search →    │
│ GET  /health │     │  assemble context → generate  │
└──────────────┘     └──────────────────────────────┘
```

## Provider Strategy

The platform uses abstract interfaces (`EmbeddingProvider`, `LLMProvider`) so the AI provider can be swapped with a config change:

| Provider | Embedding Model | LLM Model | Status |
|----------|----------------|-----------|--------|
| OpenAI | text-embedding-3-small (1536d) | gpt-4o-mini | ✅ MVP |
| Bedrock | Titan Embeddings v2 (1024d) | Claude 3 Haiku | 🔜 v2 |

## Security

- IAM least privilege (separate roles for query vs ingest)
- Secrets Manager for DB credentials (auto-managed by Aurora)
- S3 encryption (KMS) + public access blocking
- Input validation + character limits
- No secrets in code or config files

## Cost Controls

- Aurora Serverless v2: min 0.5 ACU (scales near-zero when idle)
- SHA256 document caching (skip re-embedding unchanged docs)
- Batched embedding API calls
- Configurable `max_tokens` and `top_k` limits
- Retrieval-only mode (no LLM cost for testing)
