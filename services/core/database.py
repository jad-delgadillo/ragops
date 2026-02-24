"""Database connection pool and data-access helpers for Aurora/pgvector."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg import sql
from psycopg.rows import dict_row

from services.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
VECTOR_TYPE_PATTERN = re.compile(r"^vector(?:\((\d+)\))?$")
INVALID_DSN_LITERALS = {"yes", "no", "true", "false", "on", "off", "1", "0"}
INDEX_METADATA_PREFIX = "index_metadata:"

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def get_connection(settings: Settings | None = None) -> psycopg.Connection:
    """Create a new database connection with pgvector support."""
    s = settings or get_settings()

    db_url = s.database_url or s.neon_connection_string
    if db_url:
        normalized = normalize_db_url(db_url)
        conn = psycopg.connect(
            normalized,
            row_factory=dict_row,
            autocommit=False,
        )
    else:
        conn = psycopg.connect(
            host=s.db_host,
            port=s.db_port,
            dbname=s.db_name,
            user=s.db_user,
            password=s.db_password,
            row_factory=dict_row,
            autocommit=False,
        )

    register_vector(conn)
    return conn


def normalize_db_url(db_url: str) -> str:
    """Normalize and validate DSN-style connection URL values."""
    normalized = db_url.strip()
    if not normalized:
        raise ValueError("DATABASE_URL/NEON_CONNECTION_STRING is empty")
    if normalized.lower() in INVALID_DSN_LITERALS:
        raise ValueError(
            "DATABASE_URL/NEON_CONNECTION_STRING is invalid "
            f"(received boolean-like value: {normalized!r}). "
            "Set it to a full Postgres DSN, for example: "
            "postgresql://user:pass@host/db?sslmode=require"
        )
    return normalized


def init_schema(conn: psycopg.Connection) -> None:
    """Apply the schema SQL to the database."""
    sql = SCHEMA_PATH.read_text()
    conn.execute(sql)
    conn.commit()
    logger.info("Database schema initialized")


def parse_vector_dimension(type_name: str) -> int | None:
    """Parse Postgres vector type declarations like 'vector(1536)'."""
    match = VECTOR_TYPE_PATTERN.match(type_name.strip().lower())
    if not match:
        return None
    dim = match.group(1)
    return int(dim) if dim else None


def get_chunks_embedding_dimension(conn: psycopg.Connection) -> int | None:
    """Return configured vector dimension for chunks.embedding, if fixed."""
    row = conn.execute(
        """
        SELECT format_type(a.atttypid, a.atttypmod) AS embedding_type
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = 'chunks'
          AND a.attname = 'embedding'
          AND NOT a.attisdropped
        """
    ).fetchone()
    if not row:
        return None
    return parse_vector_dimension(str(row["embedding_type"]))


def validate_embedding_dimension(conn: psycopg.Connection, provider_dimension: int) -> None:
    """Validate provider embedding size against DB schema if schema is fixed."""
    schema_dimension = get_chunks_embedding_dimension(conn)
    if schema_dimension is None:
        return
    if schema_dimension != provider_dimension:
        raise ValueError(
            "Embedding dimension mismatch: "
            f"database expects {schema_dimension}, provider returns {provider_dimension}. "
            "Use a compatible embedding provider or migrate the schema."
        )


def migrate_embedding_dimension(
    conn: psycopg.Connection,
    *,
    new_dimension: int,
) -> dict[str, Any]:
    """Migrate chunks.embedding dimension and clear stale vectors/documents.

    This operation is destructive by design because vector dimensionality changes
    invalidate existing embeddings.
    """
    if int(new_dimension) <= 0:
        raise ValueError("new_dimension must be a positive integer")

    current_dimension = get_chunks_embedding_dimension(conn)
    if current_dimension == int(new_dimension):
        return {
            "backend": "postgres",
            "previous_dimension": current_dimension,
            "new_dimension": int(new_dimension),
            "documents_deleted": 0,
            "chunks_deleted": 0,
            "changed": False,
        }

    count_row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM documents) AS documents_deleted,
            (SELECT COUNT(*) FROM chunks) AS chunks_deleted
        """
    ).fetchone()
    docs_deleted = int(count_row["documents_deleted"]) if count_row else 0
    chunks_deleted = int(count_row["chunks_deleted"]) if count_row else 0

    # Purge stale embeddings/documents first, then alter vector column type.
    conn.execute("DELETE FROM documents")
    conn.execute("DROP INDEX IF EXISTS idx_chunks_embedding")
    conn.execute(
        sql.SQL("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({})").format(
            sql.SQL(str(int(new_dimension)))
        )
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chunks_embedding
            ON chunks USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """
    )
    conn.commit()
    return {
        "backend": "postgres",
        "previous_dimension": current_dimension,
        "new_dimension": int(new_dimension),
        "documents_deleted": docs_deleted,
        "chunks_deleted": chunks_deleted,
        "changed": True,
    }


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


def ensure_meta_table(conn: psycopg.Connection) -> None:
    """Create metadata table used for storage-level run/index metadata."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ragops_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.commit()


def get_meta_value(conn: psycopg.Connection, key: str) -> str | None:
    """Return metadata value for a key or None when absent."""
    ensure_meta_table(conn)
    row = conn.execute(
        "SELECT value FROM ragops_meta WHERE key = %s",
        (key,),
    ).fetchone()
    if not row:
        return None
    value = row.get("value")
    return str(value) if value is not None else None


def upsert_meta_value(conn: psycopg.Connection, key: str, value: str) -> None:
    """Insert/update a metadata value by key."""
    ensure_meta_table(conn)
    conn.execute(
        """
        INSERT INTO ragops_meta (key, value, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (key)
        DO UPDATE SET
            value = EXCLUDED.value,
            updated_at = NOW()
        """,
        (key, value),
    )
    conn.commit()


def get_collection_index_metadata(
    conn: psycopg.Connection,
    *,
    collection: str,
) -> dict[str, Any] | None:
    """Return stored index metadata payload for a collection."""
    raw = get_meta_value(conn, f"{INDEX_METADATA_PREFIX}{collection}")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def upsert_collection_index_metadata(
    conn: psycopg.Connection,
    *,
    collection: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Persist and return index metadata payload for a collection."""
    payload = dict(metadata)
    payload["collection"] = collection
    payload.setdefault("created_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    serialized = json.dumps(payload, sort_keys=True)
    upsert_meta_value(conn, f"{INDEX_METADATA_PREFIX}{collection}", serialized)
    return payload


# ---------------------------------------------------------------------------
# Document operations
# ---------------------------------------------------------------------------


def compute_sha256(content: str) -> str:
    """Compute SHA256 hash of text content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def document_exists(conn: psycopg.Connection, sha256: str, collection: str) -> int | None:
    """Check if a document with this SHA256 already exists. Returns doc id or None."""
    row = conn.execute(
        "SELECT id FROM documents WHERE sha256 = %s AND collection = %s",
        (sha256, collection),
    ).fetchone()
    return row["id"] if row else None


def document_exists_for_index(
    conn: psycopg.Connection,
    *,
    sha256: str,
    collection: str,
    index_version: str,
) -> int | None:
    """Return doc id when sha+collection exists and matches index_version metadata."""
    row = conn.execute(
        """
        SELECT id
        FROM documents
        WHERE sha256 = %s
          AND collection = %s
          AND COALESCE(metadata->>'index_version', '') = %s
        """,
        (sha256, collection, index_version),
    ).fetchone()
    return row["id"] if row else None


def upsert_document(
    conn: psycopg.Connection,
    s3_key: str,
    sha256: str,
    collection: str = "default",
    metadata: dict[str, Any] | None = None,
) -> int:
    """Insert or update a document record. Returns the document id."""
    import json

    meta_json = json.dumps(metadata or {})
    row = conn.execute(
        """
        INSERT INTO documents (s3_key, sha256, collection, metadata)
        VALUES (%s, %s, %s, %s::jsonb)
        ON CONFLICT (sha256, collection)
        DO UPDATE SET s3_key = EXCLUDED.s3_key, metadata = EXCLUDED.metadata
        RETURNING id
        """,
        (s3_key, sha256, collection, meta_json),
    ).fetchone()
    conn.commit()
    return row["id"]  # type: ignore[index]


def purge_collection_documents(
    conn: psycopg.Connection,
    *,
    collection: str,
) -> dict[str, int]:
    """Delete documents/chunks for a collection and return deleted counts."""
    chunk_row = conn.execute(
        """
        SELECT COUNT(*) AS chunk_count
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.collection = %s
        """,
        (collection,),
    ).fetchone()
    doc_row = conn.execute(
        """
        SELECT COUNT(*) AS doc_count
        FROM documents
        WHERE collection = %s
        """,
        (collection,),
    ).fetchone()
    conn.execute(
        """
        DELETE FROM documents
        WHERE collection = %s
        """,
        (collection,),
    )
    conn.commit()
    return {
        "documents_deleted": int(doc_row["doc_count"]) if doc_row else 0,
        "chunks_deleted": int(chunk_row["chunk_count"]) if chunk_row else 0,
    }


# ---------------------------------------------------------------------------
# Chunk operations
# ---------------------------------------------------------------------------


def upsert_chunks(
    conn: psycopg.Connection,
    document_id: int,
    chunks: list[dict[str, Any]],
) -> int:
    """Insert chunks for a document. Deletes old chunks first (full re-index).

    Each chunk dict should have: content, embedding, chunk_index,
    and optionally: token_count, source_file, line_start, line_end.

    Returns the number of chunks inserted.
    """
    # Delete existing chunks for this document (re-index strategy)
    conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))

    if not chunks:
        conn.commit()
        return 0

    with conn.cursor() as cur:
        for chunk in chunks:
            cur.execute(
                """
                INSERT INTO chunks
                    (document_id, chunk_index, content, embedding,
                     token_count, source_file, line_start, line_end)
                VALUES (%s, %s, %s, %s::vector, %s, %s, %s, %s)
                """,
                (
                    document_id,
                    chunk["chunk_index"],
                    chunk["content"],
                    str(chunk["embedding"]),
                    chunk.get("token_count"),
                    chunk.get("source_file"),
                    chunk.get("line_start"),
                    chunk.get("line_end"),
                ),
            )
    conn.commit()
    logger.info("Inserted %d chunks for document %d", len(chunks), document_id)
    return len(chunks)


# ---------------------------------------------------------------------------
# Vector search
# ---------------------------------------------------------------------------


def search_vectors(
    conn: psycopg.Connection,
    query_embedding: list[float],
    collection: str = "default",
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Find the top-K most similar chunks using cosine distance.

    Returns list of dicts with: content, source_file, line_start, line_end,
    similarity, document s3_key.
    """
    rows = conn.execute(
        """
        SELECT
            c.content,
            c.source_file,
            c.line_start,
            c.line_end,
            c.chunk_index,
            d.s3_key,
            1 - (c.embedding <=> %s::vector) AS similarity
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.collection = %s
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
        """,
        (str(query_embedding), collection, str(query_embedding), top_k),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Chat session operations
# ---------------------------------------------------------------------------


def ensure_chat_tables(conn: psycopg.Connection) -> None:
    """Create chat tables if they do not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id      VARCHAR(64) PRIMARY KEY,
            collection      VARCHAR(128) NOT NULL DEFAULT 'default',
            mode            VARCHAR(64) NOT NULL DEFAULT 'default',
            metadata        JSONB DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id              BIGSERIAL PRIMARY KEY,
            session_id      VARCHAR(64) NOT NULL
                            REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
            role            VARCHAR(16) NOT NULL,
            content         TEXT NOT NULL,
            citations       JSONB DEFAULT '[]'::jsonb,
            metadata        JSONB DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chat_messages_role_check
                CHECK (role IN ('user', 'assistant', 'system'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
            ON chat_messages (session_id, id)
        """
    )
    conn.commit()


def upsert_chat_session(
    conn: psycopg.Connection,
    *,
    session_id: str,
    collection: str,
    mode: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Create or update a chat session record."""
    conn.execute(
        """
        INSERT INTO chat_sessions (session_id, collection, mode, metadata)
        VALUES (%s, %s, %s, %s::jsonb)
        ON CONFLICT (session_id)
        DO UPDATE SET
            collection = EXCLUDED.collection,
            mode = EXCLUDED.mode,
            metadata = chat_sessions.metadata || EXCLUDED.metadata,
            updated_at = NOW()
        """,
        (session_id, collection, mode, json.dumps(metadata or {})),
    )
    conn.commit()


def insert_chat_message(
    conn: psycopg.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Insert a chat message and return message id."""
    row = conn.execute(
        """
        INSERT INTO chat_messages (session_id, role, content, citations, metadata)
        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
        RETURNING id
        """,
        (
            session_id,
            role,
            content,
            json.dumps(citations or []),
            json.dumps(metadata or {}),
        ),
    ).fetchone()
    conn.execute(
        """
        UPDATE chat_sessions
        SET updated_at = NOW()
        WHERE session_id = %s
        """,
        (session_id,),
    )
    conn.commit()
    return int(row["id"])


def list_chat_messages(
    conn: psycopg.Connection,
    *,
    session_id: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Return most recent messages in chronological order."""
    rows = conn.execute(
        """
        SELECT id, session_id, role, content, citations, metadata, created_at
        FROM (
            SELECT id, session_id, role, content, citations, metadata, created_at
            FROM chat_messages
            WHERE session_id = %s
            ORDER BY id DESC
            LIMIT %s
        ) recent
        ORDER BY id ASC
        """,
        (session_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def count_chat_turns(conn: psycopg.Connection, *, session_id: str) -> int:
    """Count assistant replies as completed turns."""
    row = conn.execute(
        """
        SELECT COUNT(*) AS turns
        FROM chat_messages
        WHERE session_id = %s
          AND role = 'assistant'
        """,
        (session_id,),
    ).fetchone()
    return int(row["turns"]) if row else 0


# ---------------------------------------------------------------------------
# Feedback operations
# ---------------------------------------------------------------------------


def ensure_feedback_table(conn: psycopg.Connection) -> None:
    """Create feedback table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS answer_feedback (
            id              BIGSERIAL PRIMARY KEY,
            session_id      VARCHAR(64),
            collection      VARCHAR(128) NOT NULL DEFAULT 'default',
            mode            VARCHAR(64) NOT NULL DEFAULT 'default',
            verdict         VARCHAR(16) NOT NULL,
            question        TEXT,
            answer          TEXT,
            comment         TEXT,
            citations       JSONB DEFAULT '[]'::jsonb,
            metadata        JSONB DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT answer_feedback_verdict_check
                CHECK (verdict IN ('positive', 'negative'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_answer_feedback_collection_created
            ON answer_feedback (collection, created_at DESC)
        """
    )
    conn.commit()


def insert_feedback(
    conn: psycopg.Connection,
    *,
    verdict: str,
    collection: str = "default",
    mode: str = "default",
    session_id: str | None = None,
    question: str | None = None,
    answer: str | None = None,
    comment: str | None = None,
    citations: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Insert feedback record and return id."""
    row = conn.execute(
        """
        INSERT INTO answer_feedback (
            session_id, collection, mode, verdict, question, answer, comment, citations, metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
        RETURNING id
        """,
        (
            session_id,
            collection,
            mode,
            verdict,
            question,
            answer,
            comment,
            json.dumps(citations or []),
            json.dumps(metadata or {}),
        ),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def summarize_feedback(
    conn: psycopg.Connection,
    *,
    collection: str | None = None,
) -> dict[str, Any]:
    """Summarize feedback counts and positive rate."""
    if collection:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE verdict = 'positive') AS positive,
                COUNT(*) FILTER (WHERE verdict = 'negative') AS negative
            FROM answer_feedback
            WHERE collection = %s
            """,
            (collection,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE verdict = 'positive') AS positive,
                COUNT(*) FILTER (WHERE verdict = 'negative') AS negative
            FROM answer_feedback
            """
        ).fetchone()

    total = int(row["total"]) if row else 0
    positive = int(row["positive"]) if row else 0
    negative = int(row["negative"]) if row else 0
    positive_rate = (positive / total) if total > 0 else 0.0
    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "positive_rate": round(positive_rate, 4),
    }


# ---------------------------------------------------------------------------
# Repo onboarding job operations
# ---------------------------------------------------------------------------


def ensure_repo_onboarding_jobs_table(conn: psycopg.Connection) -> None:
    """Create repo onboarding jobs table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS repo_onboarding_jobs (
            job_id           VARCHAR(64) PRIMARY KEY,
            collection       VARCHAR(128) NOT NULL DEFAULT 'default',
            principal        VARCHAR(128) NOT NULL DEFAULT 'unknown',
            status           VARCHAR(16) NOT NULL DEFAULT 'queued',
            request_payload  JSONB NOT NULL DEFAULT '{}'::jsonb,
            result           JSONB DEFAULT '{}'::jsonb,
            error            TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at       TIMESTAMPTZ,
            finished_at      TIMESTAMPTZ,
            CONSTRAINT repo_onboarding_jobs_status_check
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_repo_onboarding_jobs_collection_created
            ON repo_onboarding_jobs (collection, created_at DESC)
        """
    )
    conn.commit()


def create_repo_onboarding_job(
    conn: psycopg.Connection,
    *,
    job_id: str,
    collection: str,
    principal: str,
    request_payload: dict[str, Any],
) -> None:
    """Insert a queued repo onboarding job."""
    conn.execute(
        """
        INSERT INTO repo_onboarding_jobs (
            job_id, collection, principal, status, request_payload
        )
        VALUES (%s, %s, %s, 'queued', %s::jsonb)
        """,
        (job_id, collection, principal, json.dumps(request_payload)),
    )
    conn.commit()


def get_repo_onboarding_job(
    conn: psycopg.Connection,
    *,
    job_id: str,
) -> dict[str, Any] | None:
    """Fetch repo onboarding job by id."""
    row = conn.execute(
        """
        SELECT
            job_id,
            collection,
            principal,
            status,
            request_payload,
            result,
            error,
            created_at,
            updated_at,
            started_at,
            finished_at
        FROM repo_onboarding_jobs
        WHERE job_id = %s
        """,
        (job_id,),
    ).fetchone()
    return dict(row) if row else None


def mark_repo_onboarding_job_running(conn: psycopg.Connection, *, job_id: str) -> None:
    """Mark repo onboarding job as running."""
    conn.execute(
        """
        UPDATE repo_onboarding_jobs
        SET
            status = 'running',
            error = NULL,
            started_at = COALESCE(started_at, NOW()),
            updated_at = NOW()
        WHERE job_id = %s
        """,
        (job_id,),
    )
    conn.commit()


def mark_repo_onboarding_job_succeeded(
    conn: psycopg.Connection,
    *,
    job_id: str,
    result: dict[str, Any],
) -> None:
    """Mark repo onboarding job as succeeded with result payload."""
    conn.execute(
        """
        UPDATE repo_onboarding_jobs
        SET
            status = 'succeeded',
            result = %s::jsonb,
            error = NULL,
            finished_at = NOW(),
            updated_at = NOW()
        WHERE job_id = %s
        """,
        (json.dumps(result), job_id),
    )
    conn.commit()


def mark_repo_onboarding_job_failed(
    conn: psycopg.Connection,
    *,
    job_id: str,
    error: str,
) -> None:
    """Mark repo onboarding job as failed with error message."""
    conn.execute(
        """
        UPDATE repo_onboarding_jobs
        SET
            status = 'failed',
            error = %s,
            finished_at = NOW(),
            updated_at = NOW()
        WHERE job_id = %s
        """,
        (error[:4000], job_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Lazy RAG — repo file tree tracking
# ---------------------------------------------------------------------------


def ensure_repo_files_table(conn: psycopg.Connection) -> None:
    """Create repo_files table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS repo_files (
            id              BIGSERIAL PRIMARY KEY,
            collection      VARCHAR(128) NOT NULL,
            owner           VARCHAR(128) NOT NULL,
            repo            VARCHAR(128) NOT NULL,
            ref             VARCHAR(128) NOT NULL DEFAULT 'main',
            file_path       TEXT NOT NULL,
            file_sha        VARCHAR(64),
            file_size       INTEGER DEFAULT 0,
            embedded        BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT repo_files_unique UNIQUE (collection, file_path)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_repo_files_collection
            ON repo_files (collection)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_repo_files_embedded
            ON repo_files (collection, embedded)
        """
    )
    conn.commit()


def upsert_file_tree(
    conn: psycopg.Connection,
    *,
    collection: str,
    owner: str,
    repo: str,
    ref: str,
    files: list[dict[str, Any]],
) -> int:
    """Bulk upsert file tree entries. Returns count of upserted rows."""
    ensure_repo_files_table(conn)
    count = 0
    with conn.cursor() as cur:
        for f in files:
            cur.execute(
                """
                INSERT INTO repo_files (
                    collection, owner, repo, ref, file_path, file_sha, file_size
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (collection, file_path)
                DO UPDATE SET
                    file_sha = EXCLUDED.file_sha,
                    file_size = EXCLUDED.file_size,
                    ref = EXCLUDED.ref
                """,
                (
                    collection,
                    owner,
                    repo,
                    ref,
                    f["path"],
                    f.get("sha", ""),
                    f.get("size", 0),
                ),
            )
            count += 1
    conn.commit()
    return count


def get_unembedded_files(
    conn: psycopg.Connection,
    *,
    collection: str,
    paths: list[str],
) -> list[str]:
    """Return subset of paths that have NOT been embedded yet."""
    ensure_repo_files_table(conn)
    if not paths:
        return []

    # Build parameterized query for the IN clause
    placeholders = ", ".join(["%s"] * len(paths))
    rows = conn.execute(
        f"""
        SELECT file_path FROM repo_files
        WHERE collection = %s
          AND file_path IN ({placeholders})
          AND embedded = FALSE
        """,
        [collection, *paths],
    ).fetchall()
    return [row["file_path"] for row in rows]


def mark_files_embedded(
    conn: psycopg.Connection,
    *,
    collection: str,
    paths: list[str],
) -> int:
    """Mark files as embedded. Returns count of updated rows."""
    if not paths:
        return 0
    placeholders = ", ".join(["%s"] * len(paths))
    result = conn.execute(
        f"""
        UPDATE repo_files
        SET embedded = TRUE
        WHERE collection = %s
          AND file_path IN ({placeholders})
        """,
        [collection, *paths],
    )
    conn.commit()
    return result.rowcount


def get_repo_meta(
    conn: psycopg.Connection,
    *,
    collection: str,
) -> dict[str, Any] | None:
    """Get owner/repo/ref metadata for a lazy-onboarded collection."""
    ensure_repo_files_table(conn)
    row = conn.execute(
        """
        SELECT owner, repo, ref, COUNT(*) AS file_count,
               COUNT(*) FILTER (WHERE embedded) AS embedded_count
        FROM repo_files
        WHERE collection = %s
        GROUP BY owner, repo, ref
        LIMIT 1
        """,
        (collection,),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def health_check(conn: psycopg.Connection) -> dict[str, str]:
    """Quick DB health check."""
    try:
        conn.execute("SELECT 1")
        return {"db": "ok"}
    except Exception as exc:
        logger.error("DB health check failed: %s", exc)
        return {"db": f"error: {exc}"}
