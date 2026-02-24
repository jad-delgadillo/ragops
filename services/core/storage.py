"""Storage abstraction for Postgres and local SQLite backends."""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services.core import database as pgdb
from services.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_DB_PATH = ".ragops/ragops.db"
INDEX_METADATA_PREFIX = "index_metadata:"
INDEX_VERSION_KEYS = (
    "repo_commit",
    "embedding_provider",
    "embedding_model",
    "chunk_size",
    "chunk_overlap",
)


def resolve_storage_backend(settings: Settings | None = None) -> str:
    """Resolve active storage backend from settings."""
    s = settings or get_settings()
    backend = (s.storage_backend or "auto").strip().lower()
    if backend in {"postgres", "postgresql", "pg", "aurora", "neon"}:
        return "postgres"
    if backend in {"sqlite", "local"}:
        return "sqlite"
    if backend not in {"", "auto"}:
        raise ValueError(f"Unsupported STORAGE_BACKEND '{s.storage_backend}'")
    if (s.database_url or "").strip() or (s.neon_connection_string or "").strip():
        return "postgres"
    if (s.environment or "").strip().lower() in {"local", "dev", "test"}:
        return "sqlite"
    return "postgres"


def _find_workspace_root(start: Path) -> Path:
    """Best-effort project root discovery for local SQLite placement."""
    current = start.resolve()
    for _ in range(20):
        if (current / ".ragops" / "config.yaml").exists():
            return current
        if (current / ".git").exists():
            return current
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return start.resolve()


def _resolve_sqlite_path(settings: Settings) -> Path:
    raw = (settings.local_db_path or "").strip() or DEFAULT_SQLITE_DB_PATH
    path = Path(raw).expanduser()
    if not path.is_absolute():
        root = _find_workspace_root(Path.cwd())
        path = (root / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _is_sqlite(conn: Any) -> bool:
    return isinstance(conn, sqlite3.Connection)


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS ragops_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            s3_key TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            collection TEXT NOT NULL DEFAULT 'default',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (sha256, collection)
        );
        CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents (collection);

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT NOT NULL,
            token_count INTEGER,
            source_file TEXT,
            line_start INTEGER,
            line_end INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_source_file ON chunks (source_file);

        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            collection TEXT NOT NULL DEFAULT 'default',
            mode TEXT NOT NULL DEFAULT 'default',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            citations TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
            ON chat_messages (session_id, id);

        CREATE TABLE IF NOT EXISTS answer_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            collection TEXT NOT NULL DEFAULT 'default',
            mode TEXT NOT NULL DEFAULT 'default',
            verdict TEXT NOT NULL,
            question TEXT,
            answer TEXT,
            comment TEXT,
            citations TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_answer_feedback_collection_created
            ON answer_feedback (collection, created_at);

        CREATE TABLE IF NOT EXISTS repo_onboarding_jobs (
            job_id TEXT PRIMARY KEY,
            collection TEXT NOT NULL DEFAULT 'default',
            principal TEXT NOT NULL DEFAULT 'unknown',
            status TEXT NOT NULL DEFAULT 'queued',
            request_payload TEXT NOT NULL DEFAULT '{}',
            result TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT,
            finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_repo_onboarding_jobs_collection_created
            ON repo_onboarding_jobs (collection, created_at);

        CREATE TABLE IF NOT EXISTS repo_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection TEXT NOT NULL,
            owner TEXT NOT NULL,
            repo TEXT NOT NULL,
            ref TEXT NOT NULL DEFAULT 'main',
            file_path TEXT NOT NULL,
            file_sha TEXT,
            file_size INTEGER DEFAULT 0,
            embedded INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (collection, file_path)
        );
        CREATE INDEX IF NOT EXISTS idx_repo_files_collection ON repo_files (collection);
        CREATE INDEX IF NOT EXISTS idx_repo_files_embedded ON repo_files (collection, embedded);
        """
    )
    conn.commit()


def _json_load(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def get_connection(settings: Settings | None = None) -> Any:
    """Create storage connection for active backend."""
    s = settings or get_settings()
    backend = resolve_storage_backend(s)
    if backend == "postgres":
        return pgdb.get_connection(s)

    sqlite_path = _resolve_sqlite_path(s)
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    _ensure_sqlite_schema(conn)
    return conn


def normalize_db_url(db_url: str) -> str:
    """Proxy database URL normalization for compatibility with existing tests."""
    return pgdb.normalize_db_url(db_url)


def parse_vector_dimension(type_name: str) -> int | None:
    """Proxy parser for compatibility with existing tests."""
    return pgdb.parse_vector_dimension(type_name)


def get_chunks_embedding_dimension(conn: Any) -> int | None:
    """Return configured embedding dimension for active backend."""
    if not _is_sqlite(conn):
        return pgdb.get_chunks_embedding_dimension(conn)
    row = conn.execute(
        "SELECT value FROM ragops_meta WHERE key = 'embedding_dimension'"
    ).fetchone()
    if not row:
        return None
    try:
        return int(row["value"])
    except Exception:
        return None


def validate_embedding_dimension(conn: Any, provider_dimension: int) -> None:
    """Validate provider embedding dimension against backend storage."""
    if not _is_sqlite(conn):
        pgdb.validate_embedding_dimension(conn, provider_dimension)
        return
    existing = get_chunks_embedding_dimension(conn)
    if existing is None:
        conn.execute(
            """
            INSERT INTO ragops_meta (key, value)
            VALUES ('embedding_dimension', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(provider_dimension),),
        )
        conn.commit()
        return
    if int(existing) != int(provider_dimension):
        raise ValueError(
            "Embedding dimension mismatch: "
            f"storage expects {existing}, provider returns {provider_dimension}. "
            "Use a compatible embedding provider or reset local DB."
        )


def migrate_embedding_dimension(
    conn: Any,
    *,
    new_dimension: int,
) -> dict[str, Any]:
    """Migrate embedding dimension for active backend and clear stale vectors."""
    if int(new_dimension) <= 0:
        raise ValueError("new_dimension must be a positive integer")

    if not _is_sqlite(conn):
        return pgdb.migrate_embedding_dimension(conn, new_dimension=int(new_dimension))

    previous_dimension = get_chunks_embedding_dimension(conn)
    if previous_dimension == int(new_dimension):
        return {
            "backend": "sqlite",
            "previous_dimension": previous_dimension,
            "new_dimension": int(new_dimension),
            "documents_deleted": 0,
            "chunks_deleted": 0,
            "changed": False,
        }

    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM documents) AS documents_deleted,
            (SELECT COUNT(*) FROM chunks) AS chunks_deleted
        """
    ).fetchone()
    docs_deleted = int(row["documents_deleted"]) if row else 0
    chunks_deleted = int(row["chunks_deleted"]) if row else 0

    # Delete stale vectors/documents and update configured dimension.
    conn.execute("DELETE FROM documents")
    conn.execute(
        """
        INSERT INTO ragops_meta (key, value)
        VALUES ('embedding_dimension', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (str(int(new_dimension)),),
    )
    conn.commit()
    return {
        "backend": "sqlite",
        "previous_dimension": previous_dimension,
        "new_dimension": int(new_dimension),
        "documents_deleted": docs_deleted,
        "chunks_deleted": chunks_deleted,
        "changed": True,
    }


def compute_sha256(content: str) -> str:
    """Compute SHA256 hash of text content."""
    return pgdb.compute_sha256(content)


def build_index_version(metadata: dict[str, Any]) -> str:
    """Build deterministic index-version hash from metadata-driving fields."""
    normalized = {key: metadata.get(key, "") for key in INDEX_VERSION_KEYS}
    serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return compute_sha256(serialized)[:16]


def get_collection_index_metadata(
    conn: Any,
    *,
    collection: str,
) -> dict[str, Any] | None:
    """Return index metadata payload for a collection."""
    if not _is_sqlite(conn):
        return pgdb.get_collection_index_metadata(conn, collection=collection)
    row = conn.execute(
        "SELECT value FROM ragops_meta WHERE key = ?",
        (f"{INDEX_METADATA_PREFIX}{collection}",),
    ).fetchone()
    if not row:
        return None
    payload = _json_load(row["value"], None)
    return payload if isinstance(payload, dict) else None


def upsert_collection_index_metadata(
    conn: Any,
    *,
    collection: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Persist and return index metadata for a collection."""
    payload = dict(metadata)
    payload["collection"] = collection
    payload["index_version"] = build_index_version(payload)
    payload.setdefault("created_at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))

    if not _is_sqlite(conn):
        return pgdb.upsert_collection_index_metadata(
            conn,
            collection=collection,
            metadata=payload,
        )

    conn.execute(
        """
        INSERT INTO ragops_meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (
            f"{INDEX_METADATA_PREFIX}{collection}",
            json.dumps(payload, sort_keys=True),
        ),
    )
    conn.commit()
    return payload


def document_exists(conn: Any, sha256: str, collection: str) -> int | None:
    """Check if a document with this SHA256 already exists."""
    if not _is_sqlite(conn):
        return pgdb.document_exists(conn, sha256, collection)
    row = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ? AND collection = ?",
        (sha256, collection),
    ).fetchone()
    return int(row["id"]) if row else None


def document_exists_for_index(
    conn: Any,
    *,
    sha256: str,
    collection: str,
    index_version: str,
) -> int | None:
    """Check if a document exists for this sha+collection+index_version."""
    if not _is_sqlite(conn):
        return pgdb.document_exists_for_index(
            conn,
            sha256=sha256,
            collection=collection,
            index_version=index_version,
        )

    row = conn.execute(
        "SELECT id, metadata FROM documents WHERE sha256 = ? AND collection = ?",
        (sha256, collection),
    ).fetchone()
    if not row:
        return None
    metadata = _json_load(row["metadata"], {})
    if not isinstance(metadata, dict):
        return None
    if str(metadata.get("index_version", "")) != str(index_version):
        return None
    return int(row["id"])


def upsert_document(
    conn: Any,
    s3_key: str,
    sha256: str,
    collection: str = "default",
    metadata: dict[str, Any] | None = None,
) -> int:
    """Insert or update document record and return id."""
    if not _is_sqlite(conn):
        return pgdb.upsert_document(
            conn,
            s3_key=s3_key,
            sha256=sha256,
            collection=collection,
            metadata=metadata,
        )
    conn.execute(
        """
        INSERT INTO documents (s3_key, sha256, collection, metadata, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (sha256, collection)
        DO UPDATE SET
            s3_key = excluded.s3_key,
            metadata = excluded.metadata,
            updated_at = CURRENT_TIMESTAMP
        """,
        (s3_key, sha256, collection, json.dumps(metadata or {})),
    )
    row = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ? AND collection = ?",
        (sha256, collection),
    ).fetchone()
    conn.commit()
    if not row:
        raise RuntimeError("failed to upsert document")
    return int(row["id"])


def purge_collection_documents(
    conn: Any,
    *,
    collection: str,
) -> dict[str, int]:
    """Delete documents/chunks for a collection and return deleted counts."""
    if not _is_sqlite(conn):
        return pgdb.purge_collection_documents(conn, collection=collection)
    chunk_row = conn.execute(
        """
        SELECT COUNT(*) AS chunk_count
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.collection = ?
        """,
        (collection,),
    ).fetchone()
    doc_row = conn.execute(
        "SELECT COUNT(*) AS doc_count FROM documents WHERE collection = ?",
        (collection,),
    ).fetchone()
    conn.execute("DELETE FROM documents WHERE collection = ?", (collection,))
    conn.commit()
    return {
        "documents_deleted": int(doc_row["doc_count"]) if doc_row else 0,
        "chunks_deleted": int(chunk_row["chunk_count"]) if chunk_row else 0,
    }


def upsert_chunks(conn: Any, document_id: int, chunks: list[dict[str, Any]]) -> int:
    """Insert chunks for a document, replacing existing rows for the doc."""
    if not _is_sqlite(conn):
        return pgdb.upsert_chunks(conn, document_id=document_id, chunks=chunks)
    conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
    if not chunks:
        conn.commit()
        return 0
    conn.executemany(
        """
        INSERT INTO chunks (
            document_id, chunk_index, content, embedding,
            token_count, source_file, line_start, line_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                document_id,
                chunk["chunk_index"],
                chunk["content"],
                json.dumps(chunk["embedding"]),
                chunk.get("token_count"),
                chunk.get("source_file"),
                chunk.get("line_start"),
                chunk.get("line_end"),
            )
            for chunk in chunks
        ],
    )
    conn.commit()
    return len(chunks)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_vectors(
    conn: Any,
    query_embedding: list[float],
    collection: str = "default",
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Return top-K similar chunks."""
    if not _is_sqlite(conn):
        return pgdb.search_vectors(
            conn,
            query_embedding=query_embedding,
            collection=collection,
            top_k=top_k,
        )
    rows = conn.execute(
        """
        SELECT
            c.content,
            c.source_file,
            c.line_start,
            c.line_end,
            c.chunk_index,
            c.embedding,
            d.s3_key
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.collection = ?
        """,
        (collection,),
    ).fetchall()

    scored: list[dict[str, Any]] = []
    for row in rows:
        embedding = _json_load(row["embedding"], [])
        if not isinstance(embedding, list):
            continue
        try:
            vector = [float(v) for v in embedding]
        except Exception:
            continue
        similarity = _cosine_similarity(query_embedding, vector)
        scored.append(
            {
                "content": row["content"],
                "source_file": row["source_file"],
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "chunk_index": row["chunk_index"],
                "s3_key": row["s3_key"],
                "similarity": similarity,
            }
        )

    scored.sort(key=lambda item: float(item.get("similarity", 0.0)), reverse=True)
    return scored[: max(1, top_k)]


def ensure_chat_tables(conn: Any) -> None:
    """Create chat tables for active backend."""
    if not _is_sqlite(conn):
        pgdb.ensure_chat_tables(conn)
        return
    _ensure_sqlite_schema(conn)


def upsert_chat_session(
    conn: Any,
    *,
    session_id: str,
    collection: str,
    mode: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Create or update a chat session record."""
    if not _is_sqlite(conn):
        pgdb.upsert_chat_session(
            conn,
            session_id=session_id,
            collection=collection,
            mode=mode,
            metadata=metadata,
        )
        return
    existing = conn.execute(
        "SELECT metadata FROM chat_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    existing_meta = _json_load(existing["metadata"], {}) if existing else {}
    merged_meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
    merged_meta.update(metadata or {})
    conn.execute(
        """
        INSERT INTO chat_sessions (session_id, collection, mode, metadata, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(session_id)
        DO UPDATE SET
            collection = excluded.collection,
            mode = excluded.mode,
            metadata = excluded.metadata,
            updated_at = CURRENT_TIMESTAMP
        """,
        (session_id, collection, mode, json.dumps(merged_meta)),
    )
    conn.commit()


def insert_chat_message(
    conn: Any,
    *,
    session_id: str,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Insert a chat message and return message id."""
    if not _is_sqlite(conn):
        return pgdb.insert_chat_message(
            conn,
            session_id=session_id,
            role=role,
            content=content,
            citations=citations,
            metadata=metadata,
        )
    cur = conn.execute(
        """
        INSERT INTO chat_messages (session_id, role, content, citations, metadata)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            session_id,
            role,
            content,
            json.dumps(citations or []),
            json.dumps(metadata or {}),
        ),
    )
    conn.execute(
        "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_chat_messages(
    conn: Any,
    *,
    session_id: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Return recent messages in chronological order."""
    if not _is_sqlite(conn):
        return pgdb.list_chat_messages(conn, session_id=session_id, limit=limit)
    rows = conn.execute(
        """
        SELECT id, session_id, role, content, citations, metadata, created_at
        FROM (
            SELECT id, session_id, role, content, citations, metadata, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
        ) recent
        ORDER BY id ASC
        """,
        (session_id, limit),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "role": row["role"],
                "content": row["content"],
                "citations": _json_load(row["citations"], []),
                "metadata": _json_load(row["metadata"], {}),
                "created_at": row["created_at"],
            }
        )
    return out


def count_chat_turns(conn: Any, *, session_id: str) -> int:
    """Count assistant replies as completed turns."""
    if not _is_sqlite(conn):
        return pgdb.count_chat_turns(conn, session_id=session_id)
    row = conn.execute(
        """
        SELECT COUNT(*) AS turns
        FROM chat_messages
        WHERE session_id = ?
          AND role = 'assistant'
        """,
        (session_id,),
    ).fetchone()
    return int(row["turns"]) if row else 0


def ensure_feedback_table(conn: Any) -> None:
    """Ensure feedback table exists."""
    if not _is_sqlite(conn):
        pgdb.ensure_feedback_table(conn)
        return
    _ensure_sqlite_schema(conn)


def insert_feedback(
    conn: Any,
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
    if not _is_sqlite(conn):
        return pgdb.insert_feedback(
            conn,
            verdict=verdict,
            collection=collection,
            mode=mode,
            session_id=session_id,
            question=question,
            answer=answer,
            comment=comment,
            citations=citations,
            metadata=metadata,
        )
    cur = conn.execute(
        """
        INSERT INTO answer_feedback (
            session_id, collection, mode, verdict, question, answer, comment, citations, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    )
    conn.commit()
    return int(cur.lastrowid)


def summarize_feedback(
    conn: Any,
    *,
    collection: str | None = None,
) -> dict[str, Any]:
    """Summarize feedback counts and positive rate."""
    if not _is_sqlite(conn):
        return pgdb.summarize_feedback(conn, collection=collection)
    if collection:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN verdict = 'positive' THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN verdict = 'negative' THEN 1 ELSE 0 END) AS negative
            FROM answer_feedback
            WHERE collection = ?
            """,
            (collection,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN verdict = 'positive' THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN verdict = 'negative' THEN 1 ELSE 0 END) AS negative
            FROM answer_feedback
            """
        ).fetchone()
    total = int(row["total"]) if row else 0
    positive = int(row["positive"] or 0) if row else 0
    negative = int(row["negative"] or 0) if row else 0
    positive_rate = (positive / total) if total else 0.0
    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "positive_rate": round(positive_rate, 4),
    }


def ensure_repo_onboarding_jobs_table(conn: Any) -> None:
    """Ensure repo onboarding jobs table exists."""
    if not _is_sqlite(conn):
        pgdb.ensure_repo_onboarding_jobs_table(conn)
        return
    _ensure_sqlite_schema(conn)


def create_repo_onboarding_job(
    conn: Any,
    *,
    job_id: str,
    collection: str,
    principal: str,
    request_payload: dict[str, Any],
) -> None:
    """Insert a queued onboarding job."""
    if not _is_sqlite(conn):
        pgdb.create_repo_onboarding_job(
            conn,
            job_id=job_id,
            collection=collection,
            principal=principal,
            request_payload=request_payload,
        )
        return
    conn.execute(
        """
        INSERT INTO repo_onboarding_jobs (
            job_id, collection, principal, status, request_payload, updated_at
        ) VALUES (?, ?, ?, 'queued', ?, CURRENT_TIMESTAMP)
        """,
        (job_id, collection, principal, json.dumps(request_payload)),
    )
    conn.commit()


def get_repo_onboarding_job(
    conn: Any,
    *,
    job_id: str,
) -> dict[str, Any] | None:
    """Fetch repo onboarding job by id."""
    if not _is_sqlite(conn):
        return pgdb.get_repo_onboarding_job(conn, job_id=job_id)
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
        WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "job_id": row["job_id"],
        "collection": row["collection"],
        "principal": row["principal"],
        "status": row["status"],
        "request_payload": _json_load(row["request_payload"], {}),
        "result": _json_load(row["result"], {}),
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def mark_repo_onboarding_job_running(conn: Any, *, job_id: str) -> None:
    """Mark repo onboarding job as running."""
    if not _is_sqlite(conn):
        pgdb.mark_repo_onboarding_job_running(conn, job_id=job_id)
        return
    conn.execute(
        """
        UPDATE repo_onboarding_jobs
        SET
            status = 'running',
            error = NULL,
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE job_id = ?
        """,
        (job_id,),
    )
    conn.commit()


def mark_repo_onboarding_job_succeeded(
    conn: Any,
    *,
    job_id: str,
    result: dict[str, Any],
) -> None:
    """Mark repo onboarding job as succeeded with payload."""
    if not _is_sqlite(conn):
        pgdb.mark_repo_onboarding_job_succeeded(conn, job_id=job_id, result=result)
        return
    conn.execute(
        """
        UPDATE repo_onboarding_jobs
        SET
            status = 'succeeded',
            result = ?,
            error = NULL,
            finished_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE job_id = ?
        """,
        (json.dumps(result), job_id),
    )
    conn.commit()


def mark_repo_onboarding_job_failed(
    conn: Any,
    *,
    job_id: str,
    error: str,
) -> None:
    """Mark repo onboarding job as failed with error text."""
    if not _is_sqlite(conn):
        pgdb.mark_repo_onboarding_job_failed(conn, job_id=job_id, error=error)
        return
    conn.execute(
        """
        UPDATE repo_onboarding_jobs
        SET
            status = 'failed',
            error = ?,
            finished_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE job_id = ?
        """,
        (error[:4000], job_id),
    )
    conn.commit()


def ensure_repo_files_table(conn: Any) -> None:
    """Ensure lazy repo-files table exists."""
    if not _is_sqlite(conn):
        pgdb.ensure_repo_files_table(conn)
        return
    _ensure_sqlite_schema(conn)


def upsert_file_tree(
    conn: Any,
    *,
    collection: str,
    owner: str,
    repo: str,
    ref: str,
    files: list[dict[str, Any]],
) -> int:
    """Bulk upsert lazy file-tree rows."""
    if not _is_sqlite(conn):
        return pgdb.upsert_file_tree(
            conn,
            collection=collection,
            owner=owner,
            repo=repo,
            ref=ref,
            files=files,
        )
    ensure_repo_files_table(conn)
    count = 0
    for entry in files:
        conn.execute(
            """
            INSERT INTO repo_files (collection, owner, repo, ref, file_path, file_sha, file_size)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(collection, file_path)
            DO UPDATE SET
                file_sha = excluded.file_sha,
                file_size = excluded.file_size,
                ref = excluded.ref
            """,
            (
                collection,
                owner,
                repo,
                ref,
                entry["path"],
                entry.get("sha", ""),
                entry.get("size", 0),
            ),
        )
        count += 1
    conn.commit()
    return count


def get_unembedded_files(
    conn: Any,
    *,
    collection: str,
    paths: list[str],
) -> list[str]:
    """Return subset of paths that are not embedded."""
    if not _is_sqlite(conn):
        return pgdb.get_unembedded_files(conn, collection=collection, paths=paths)
    ensure_repo_files_table(conn)
    if not paths:
        return []
    placeholders = ", ".join(["?"] * len(paths))
    rows = conn.execute(
        f"""
        SELECT file_path FROM repo_files
        WHERE collection = ?
          AND file_path IN ({placeholders})
          AND embedded = 0
        """,
        [collection, *paths],
    ).fetchall()
    return [str(row["file_path"]) for row in rows]


def mark_files_embedded(
    conn: Any,
    *,
    collection: str,
    paths: list[str],
) -> int:
    """Mark lazy file entries as embedded."""
    if not _is_sqlite(conn):
        return pgdb.mark_files_embedded(conn, collection=collection, paths=paths)
    if not paths:
        return 0
    placeholders = ", ".join(["?"] * len(paths))
    cur = conn.execute(
        f"""
        UPDATE repo_files
        SET embedded = 1
        WHERE collection = ?
          AND file_path IN ({placeholders})
        """,
        [collection, *paths],
    )
    conn.commit()
    return int(cur.rowcount)


def get_repo_meta(
    conn: Any,
    *,
    collection: str,
) -> dict[str, Any] | None:
    """Return owner/repo/ref metadata for a lazy collection."""
    if not _is_sqlite(conn):
        return pgdb.get_repo_meta(conn, collection=collection)
    ensure_repo_files_table(conn)
    row = conn.execute(
        """
        SELECT
            owner,
            repo,
            ref,
            COUNT(*) AS file_count,
            SUM(CASE WHEN embedded = 1 THEN 1 ELSE 0 END) AS embedded_count
        FROM repo_files
        WHERE collection = ?
        GROUP BY owner, repo, ref
        LIMIT 1
        """,
        (collection,),
    ).fetchone()
    if not row:
        return None
    return {
        "owner": row["owner"],
        "repo": row["repo"],
        "ref": row["ref"],
        "file_count": int(row["file_count"] or 0),
        "embedded_count": int(row["embedded_count"] or 0),
    }


def health_check(conn: Any) -> dict[str, str]:
    """Quick storage health check."""
    if not _is_sqlite(conn):
        return pgdb.health_check(conn)
    try:
        conn.execute("SELECT 1")
        return {"db": "ok"}
    except Exception as exc:
        logger.error("SQLite health check failed: %s", exc)
        return {"db": f"error: {exc}"}
