"""Tests for storage backend resolution and SQLite operations."""

from __future__ import annotations

from pathlib import Path

from services.core.config import Settings
from services.core.storage import (
    build_index_version,
    count_chat_turns,
    document_exists_for_index,
    ensure_chat_tables,
    ensure_feedback_table,
    get_collection_index_metadata,
    get_connection,
    insert_chat_message,
    insert_feedback,
    list_chat_messages,
    resolve_storage_backend,
    search_vectors,
    upsert_chat_session,
    upsert_chunks,
    upsert_collection_index_metadata,
    upsert_document,
    validate_embedding_dimension,
)


def _sqlite_settings(db_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        OPENAI_API_KEY="test",
        STORAGE_BACKEND="sqlite",
        LOCAL_DB_PATH=str(db_path),
        DATABASE_URL="",
        NEON_CONNECTION_STRING="",
        ENVIRONMENT="local",
    )


def test_resolve_storage_backend_auto_uses_sqlite_for_local_without_dsn() -> None:
    settings = Settings(
        _env_file=None,
        OPENAI_API_KEY="test",
        STORAGE_BACKEND="auto",
        DATABASE_URL="",
        NEON_CONNECTION_STRING="",
        ENVIRONMENT="local",
    )
    assert resolve_storage_backend(settings) == "sqlite"


def test_sqlite_upsert_and_search_vectors(tmp_path: Path) -> None:
    settings = _sqlite_settings(tmp_path / "ragops.db")
    conn = get_connection(settings)
    try:
        validate_embedding_dimension(conn, 3)
        doc_id = upsert_document(
            conn,
            s3_key="README.md",
            sha256="sha-readme",
            collection="demo",
            metadata={"filename": "README.md"},
        )
        upsert_chunks(
            conn,
            doc_id,
            [
                {
                    "chunk_index": 0,
                    "content": "RAG Ops overview",
                    "embedding": [1.0, 0.0, 0.0],
                    "token_count": 3,
                    "source_file": "README.md",
                    "line_start": 1,
                    "line_end": 5,
                },
                {
                    "chunk_index": 1,
                    "content": "Unrelated section",
                    "embedding": [0.0, 1.0, 0.0],
                    "token_count": 2,
                    "source_file": "README.md",
                    "line_start": 6,
                    "line_end": 10,
                },
            ],
        )
        hits = search_vectors(conn, [1.0, 0.0, 0.0], collection="demo", top_k=2)
    finally:
        conn.close()

    assert len(hits) == 2
    assert hits[0]["content"] == "RAG Ops overview"
    assert float(hits[0]["similarity"]) >= float(hits[1]["similarity"])


def test_sqlite_chat_and_feedback_roundtrip(tmp_path: Path) -> None:
    settings = _sqlite_settings(tmp_path / "ragops.db")
    conn = get_connection(settings)
    try:
        ensure_chat_tables(conn)
        upsert_chat_session(
            conn,
            session_id="s1",
            collection="demo",
            mode="default",
            metadata={"source": "test"},
        )
        insert_chat_message(conn, session_id="s1", role="user", content="hello")
        insert_chat_message(
            conn,
            session_id="s1",
            role="assistant",
            content="hi",
            citations=[{"source": "README.md"}],
        )
        messages = list_chat_messages(conn, session_id="s1", limit=10)
        turns = count_chat_turns(conn, session_id="s1")

        ensure_feedback_table(conn)
        feedback_id = insert_feedback(
            conn,
            verdict="positive",
            collection="demo",
            question="q",
            answer="a",
            comment="good",
            citations=[{"source": "README.md"}],
            metadata={"origin": "test"},
        )
    finally:
        conn.close()

    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert turns == 1
    assert feedback_id > 0


def test_index_version_changes_when_chunking_changes() -> None:
    base = {
        "repo_commit": "abc123",
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
        "chunk_size": 512,
        "chunk_overlap": 64,
    }
    v1 = build_index_version(base)
    v2 = build_index_version({**base, "chunk_size": 256})
    assert v1 != v2


def test_sqlite_index_metadata_roundtrip(tmp_path: Path) -> None:
    settings = _sqlite_settings(tmp_path / "ragops.db")
    conn = get_connection(settings)
    try:
        saved = upsert_collection_index_metadata(
            conn,
            collection="demo",
            metadata={
                "repo_commit": "abc123",
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-small",
                "chunk_size": 512,
                "chunk_overlap": 64,
            },
        )
        loaded = get_collection_index_metadata(conn, collection="demo")
    finally:
        conn.close()

    assert loaded is not None
    assert loaded["collection"] == "demo"
    assert loaded["repo_commit"] == "abc123"
    assert loaded["embedding_provider"] == "openai"
    assert loaded["embedding_model"] == "text-embedding-3-small"
    assert loaded["index_version"] == saved["index_version"]


def test_document_exists_for_index_requires_matching_version(tmp_path: Path) -> None:
    settings = _sqlite_settings(tmp_path / "ragops.db")
    conn = get_connection(settings)
    try:
        doc_id = upsert_document(
            conn,
            s3_key="README.md",
            sha256="sha-readme",
            collection="demo",
            metadata={"index_version": "v1"},
        )
        same = document_exists_for_index(
            conn,
            sha256="sha-readme",
            collection="demo",
            index_version="v1",
        )
        other = document_exists_for_index(
            conn,
            sha256="sha-readme",
            collection="demo",
            index_version="v2",
        )
    finally:
        conn.close()

    assert same == doc_id
    assert other is None
