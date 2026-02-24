# API Contract

## Base URL
- **Local**: `http://localhost:8000`
- **AWS**: `https://{api-id}.execute-api.{region}.amazonaws.com/{stage}`

## Authentication (Optional)
If `API_AUTH_ENABLED=true`, send `X-API-Key` on protected endpoints:
- `POST /v1/query`
- `POST /v1/chat`
- `POST /v1/feedback`
- `POST /v1/ingest`

Example header:
```http
X-API-Key: your-api-key
```

---

## POST /v1/ingest

Ingest documents into the vector store.

**Request:**
```json
{
  "local_dir": "./docs",
  "collection": "default"
}
```
For AWS: use `"s3_prefix": "docs/"` instead of `local_dir`.
Current status: `s3_prefix` ingestion returns `501 Not Implemented`; use `local_dir` for now.

**Response (200):**
```json
{
  "status": "ok",
  "indexed_docs": 12,
  "skipped_docs": 3,
  "chunks": 842,
  "elapsed_ms": 15230.5,
  "errors": []
}
```

---

## POST /v1/query

Query the RAG system.

**Request:**
```json
{
  "question": "How do I deploy this?",
  "collection": "default"
}
```

**Response (200):**
```json
{
  "answer": "To deploy, run terraform apply...",
  "citations": [
    {
      "source": "docs/runbooks.md",
      "line_start": 40,
      "line_end": 88,
      "similarity": 0.8923
    }
  ],
  "latency_ms": 512.3,
  "retrieved": 5,
  "retrieval_confidence": 0.78,
  "retrieval_confidence_label": "high",
  "mode": "retrieval",
  "principal": "api_client"
}
```

**Modes:**
- `retrieval`: returns top chunk as answer (no LLM)
- `rag`: generates answer using LLM with context (requires `LLM_ENABLED=true`)

`retrieval_confidence` is a heuristic score in `[0,1]` derived from top similarity values and
retrieved coverage. It is a diagnostic signal, not a correctness guarantee.

---

## POST /v1/chat

Conversational query endpoint with persisted `session_id` memory.

**Request:**
```json
{
  "question": "Where should I start as a new engineer?",
  "collection": "default",
  "session_id": "optional-existing-session",
  "mode": "explain_like_junior",
  "answer_style": "concise",
  "top_k": 5,
  "include_context": true
}
```

`mode` options:
- `default`
- `explain_like_junior`
- `show_where_in_code`
- `step_by_step`

`answer_style` options:
- `concise`
- `detailed`

**Response (200):**
```json
{
  "session_id": "c6393277-0099-4e2a-8cb5-53f72697fbce",
  "answer": "Start with services/cli/main.py ...",
  "citations": [
    {
      "source": "services/cli/main.py",
      "line_start": 1,
      "line_end": 200,
      "similarity": 0.8123
    }
  ],
  "latency_ms": 620.5,
  "retrieved": 5,
  "mode": "explain_like_junior",
  "answer_style": "concise",
  "turn_index": 3,
  "principal": "api_client",
  "context_snippets": [
    {
      "source": "services/cli/main.py",
      "line_start": 260,
      "line_end": 420,
      "similarity": 0.8123,
      "content": "def cmd_chat(args: argparse.Namespace) -> None: ..."
    }
  ]
}
```

---

## POST /v1/feedback

Capture user quality feedback for answer analytics.

**Request:**
```json
{
  "verdict": "positive",
  "collection": "default",
  "session_id": "c6393277-0099-4e2a-8cb5-53f72697fbce",
  "mode": "explain_like_junior",
  "question": "Where should I start?",
  "answer": "Start with services/cli/main.py ...",
  "comment": "Helpful and specific",
  "citations": [],
  "metadata": {"source": "web-ui"}
}
```

**Response (200):**
```json
{
  "status": "ok",
  "feedback_id": 42,
  "principal": "api_client",
  "collection": "default"
}
```

---

## GET /health

**Response (200):**
```json
{
  "status": "ok",
  "db": "ok",
  "embed": "ok"
}
```

---

## Error Responses

All errors return JSON:
```json
{
  "error": "Description of the error"
}
```

| Status | Meaning |
|--------|---------|
| 400 | Bad request (missing fields, too long) |
| 403 | Forbidden (API key missing/invalid/no collection access) |
| 500 | Internal error |
| 503 | Service degraded (DB down) |
