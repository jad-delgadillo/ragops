# API Manual

## HTTP Endpoints
| Method | Path | Summary | Source |
| --- | --- | --- | --- |
| - | - | No API endpoints discovered | - |

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
