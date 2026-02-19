"""Ingestion pipeline: read files → chunk → embed → upsert into pgvector."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.core.config import Settings, get_settings
from services.core.logging import emit_metric, timed_metric
from services.core.providers import EmbeddingProvider
from services.core.storage import (
    compute_sha256,
    document_exists,
    get_connection,
    upsert_chunks,
    upsert_document,
    validate_embedding_dimension,
)
from services.ingest.app.chunker import chunk_text, normalize_text

logger = logging.getLogger(__name__)


@dataclass
class IngestStats:
    """Statistics from an ingestion run."""

    indexed_docs: int = 0
    skipped_docs: int = 0
    total_chunks: int = 0
    elapsed_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


SUPPORTED_EXTENSIONS = {
    # Docs
    ".md",
    ".txt",
    ".rst",
    ".adoc",
    ".pdf",
    ".docx",
    # Code
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".swift",
    ".c",
    ".cpp",
    ".h",
    ".cs",
    ".scala",
    # Config
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".csv",
    ".env.example",
}

IGNORE_DIRS = {
    "__pycache__",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".pytest_cache",
    ".mypy_cache",
    ".ragops",
    ".terraform",
}
IGNORE_DIR_SUFFIXES = (".egg-info",)


def should_ignore_dir_part(
    part: str,
    ignore_dirs: set[str],
    *,
    extra_ignore_dirs: set[str] | None = None,
) -> bool:
    """Return True when a directory segment should be excluded."""
    if part in ignore_dirs:
        return True
    if extra_ignore_dirs and part in extra_ignore_dirs:
        return True
    return any(part.endswith(suffix) for suffix in IGNORE_DIR_SUFFIXES)


def should_ignore_file(
    file_path: Path,
    root_dir: Path,
    ignore_dirs: set[str],
    *,
    extra_ignore_dirs: set[str] | None = None,
) -> bool:
    """Return True if file should be ignored based on relative directory parts."""
    relative_parts = file_path.relative_to(root_dir).parts
    parent_parts = relative_parts[:-1]
    return any(
        should_ignore_dir_part(
            part,
            ignore_dirs,
            extra_ignore_dirs=extra_ignore_dirs,
        )
        for part in parent_parts
    )


def collect_ingest_files(
    directory: Path,
    *,
    extra_ignore_dirs: set[str] | None = None,
    include_paths: set[str] | None = None,
) -> list[Path]:
    """Collect files eligible for ingestion under the provided directory."""
    include_set = (
        {p.replace("\\", "/").lstrip("./") for p in include_paths}
        if include_paths is not None
        else None
    )
    files: list[Path] = []
    for candidate in directory.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if should_ignore_file(
            candidate,
            directory,
            IGNORE_DIRS,
            extra_ignore_dirs=extra_ignore_dirs,
        ):
            continue
        if include_set is not None:
            rel = candidate.relative_to(directory).as_posix()
            if rel not in include_set:
                continue
        files.append(candidate)
    return files


def ingest_local_directory(
    directory: str | Path,
    embedding_provider: EmbeddingProvider,
    collection: str = "default",
    settings: Settings | None = None,
    extra_ignore_dirs: set[str] | None = None,
    include_paths: set[str] | None = None,
) -> IngestStats:
    """Ingest all text files from a local directory.

    Args:
        directory: Path to directory containing documents.
        embedding_provider: Provider to generate embeddings.
        collection: Collection name for grouping documents.
        settings: Optional settings override.
        extra_ignore_dirs: Optional additional relative directories to ignore.
        include_paths: Optional relative paths to ingest (incremental mode).

    Returns:
        IngestStats with counts and timing.
    """
    s = settings or get_settings()
    stats = IngestStats()
    start = time.perf_counter()

    dir_path = Path(directory)
    if not dir_path.is_dir():
        stats.errors.append(f"Directory not found: {directory}")
        return stats

    # Collect text/code/config files with relative ignore rules
    files = collect_ingest_files(
        dir_path,
        extra_ignore_dirs=extra_ignore_dirs,
        include_paths=include_paths,
    )

    if not files:
        logger.warning("No text files found in %s", directory)
        return stats

    logger.info("Found %d files to ingest from %s", len(files), directory)

    conn = get_connection(s)
    try:
        validate_embedding_dimension(conn, embedding_provider.dimension)
        for file_path in files:
            try:
                _ingest_file(
                    conn=conn,
                    file_path=file_path,
                    embedding_provider=embedding_provider,
                    collection=collection,
                    stats=stats,
                    settings=s,
                )
            except Exception as exc:
                error_msg = f"Error ingesting {file_path}: {exc}"
                logger.error(error_msg)
                stats.errors.append(error_msg)
    finally:
        conn.close()

    stats.elapsed_ms = (time.perf_counter() - start) * 1000
    emit_metric("RagOps", "IngestDocsIndexed", stats.indexed_docs)
    logger.info(
        "Ingestion complete: %d indexed, %d skipped, %d chunks in %.0fms",
        stats.indexed_docs,
        stats.skipped_docs,
        stats.total_chunks,
        stats.elapsed_ms,
    )
    return stats


def _ingest_file(
    conn: Any,
    file_path: Path,
    embedding_provider: EmbeddingProvider,
    collection: str,
    stats: IngestStats,
    settings: Settings,
) -> None:
    """Ingest a single file: extract text → chunk → embed → upsert."""
    suffix = file_path.suffix.lower()
    raw_text = ""

    # 1. Extract text based on file type
    try:
        if suffix == ".pdf":
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            raw_text = "\n".join([page.get_text() for page in doc])
            doc.close()
        elif suffix == ".docx":
            import docx

            doc = docx.Document(file_path)
            raw_text = "\n".join([p.text for p in doc.paragraphs])
        else:
            # Default to text/code
            raw_text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.error("Extraction error for %s: %s", file_path, e)
        stats.errors.append(f"Extraction error ({file_path.name}): {e}")
        return

    text = normalize_text(raw_text)

    if not text:
        logger.debug("Skipping empty (or unextractable) file: %s", file_path)
        return

    sha = compute_sha256(text)

    # SHA256 caching — skip unchanged docs
    if document_exists(conn, sha, collection):
        logger.debug("Skipping unchanged doc: %s (sha=%s)", file_path, sha[:12])
        stats.skipped_docs += 1
        return

    # Chunk the text
    chunks = chunk_text(
        text,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        source_file=str(file_path),
    )

    if not chunks:
        logger.debug("No chunks produced from %s", file_path)
        return

    # Embed all chunks in batch
    chunk_texts = [c.content for c in chunks]
    with timed_metric("RagOps", "EmbeddingLatencyMs"):
        embeddings = embedding_provider.embed(chunk_texts)

    # Upsert document
    doc_id = upsert_document(
        conn,
        s3_key=str(file_path),
        sha256=sha,
        collection=collection,
        metadata={"filename": file_path.name, "size_bytes": file_path.stat().st_size},
    )

    # Build chunk records
    chunk_records = [
        {
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "embedding": emb,
            "token_count": chunk.token_count,
            "source_file": chunk.source_file,
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
        }
        for chunk, emb in zip(chunks, embeddings)
    ]

    # Upsert chunks
    inserted = upsert_chunks(conn, doc_id, chunk_records)
    stats.indexed_docs += 1
    stats.total_chunks += inserted
    logger.info("Indexed %s: %d chunks", file_path.name, inserted)
