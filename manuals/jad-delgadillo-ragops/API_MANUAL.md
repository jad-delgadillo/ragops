# API Manual

## HTTP Endpoints
| Method | Path | Summary | Source |
| --- | --- | --- | --- |
| GET | `/` | Service root and endpoint discovery | `services/api/app/handler.py` |
| GET | `/health` | Database and embedding health check | `services/api/app/handler.py` |
| POST | `/v1/query` | Retrieve and optionally generate grounded answer | `services/api/app/handler.py` |
| POST | `/v1/chat` | Conversational RAG with session memory and chat modes | `services/api/app/handler.py` |
| POST | `/v1/feedback` | Capture user feedback for answer quality analytics | `services/api/app/handler.py` |
| POST | `/v1/ingest` | Ingest local directory; s3_prefix currently returns 501 | `services/ingest/app/handler.py` |

## Request Examples
### Query
```json
{
  "question": "How does ingestion work?",
  "collection": "default"
}
```

### Ingest (Local Directory)
```json
{
  "local_dir": "./docs",
  "collection": "default"
}
```

## CLI Interface
| Command | Summary |
| --- | --- |
| `ragops init` | Initialize ragops project config |
| `ragops ingest` | Index docs/code into vector store |
| `ragops query` | Ask grounded questions |
| `ragops generate-docs` | Generate LLM-written docs from code context |
| `ragops generate-manuals` | Generate deterministic onboarding manuals |
| `ragops feedback` | Store answer quality feedback |
| `ragops eval` | Run dataset-driven quality evaluation |
| `ragops providers` | Show provider support and active config |

## Current Constraints
1. `POST /v1/ingest` with `s3_prefix` is not implemented yet.
2. `POST /v1/query` enforces a 2000-character limit on `question`.
3. Retrieval quality depends on chunking config and embedding/provider compatibility.
