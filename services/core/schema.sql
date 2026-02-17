-- RAG Ops Platform — Database Schema
-- Requires: PostgreSQL 16+ with pgvector extension

-- Enable vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ----------------------------------------------------------------
-- Documents table — tracks ingested source files
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id              BIGSERIAL PRIMARY KEY,
    s3_key          TEXT NOT NULL,
    sha256          VARCHAR(64) NOT NULL,
    collection      VARCHAR(128) NOT NULL DEFAULT 'default',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha256
    ON documents (sha256, collection);

CREATE INDEX IF NOT EXISTS idx_documents_collection
    ON documents (collection);

-- ----------------------------------------------------------------
-- Chunks table — stores text chunks with embeddings
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id              BIGSERIAL PRIMARY KEY,
    document_id     BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    embedding       vector(1536),          -- OpenAI text-embedding-3-small dimension
    token_count     INTEGER,
    source_file     TEXT,
    line_start      INTEGER,
    line_end        INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON chunks (document_id);

-- IVFFlat vector index for approximate nearest-neighbor search
-- NOTE: Requires ≥100 rows to build effectively; use exact search for small datasets
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ----------------------------------------------------------------
-- Chat sessions and messages — conversational memory
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id      VARCHAR(64) PRIMARY KEY,
    collection      VARCHAR(128) NOT NULL DEFAULT 'default',
    mode            VARCHAR(64) NOT NULL DEFAULT 'default',
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id              BIGSERIAL PRIMARY KEY,
    session_id      VARCHAR(64) NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    role            VARCHAR(16) NOT NULL,
    content         TEXT NOT NULL,
    citations       JSONB DEFAULT '[]'::jsonb,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chat_messages_role_check
        CHECK (role IN ('user', 'assistant', 'system'))
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
    ON chat_messages (session_id, id);

-- ----------------------------------------------------------------
-- Feedback table — user quality signals
-- ----------------------------------------------------------------
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
);

CREATE INDEX IF NOT EXISTS idx_answer_feedback_collection_created
    ON answer_feedback (collection, created_at DESC);
