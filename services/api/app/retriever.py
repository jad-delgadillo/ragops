"""Query retriever: embed question → vector search → assemble context with citations."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from services.api.app.ownership import ownership_bonus_for_source, tokenize_question
from services.core.config import Settings, get_settings
from services.core.logging import timed_metric
from services.core.providers import EmbeddingProvider, LLMProvider
from services.core.storage import get_connection, search_vectors, validate_embedding_dimension

logger = logging.getLogger(__name__)

BROAD_QUERY_TERMS = {
    "architecture",
    "arquitecture",  # common typo
    "overview",
    "system",
    "design",
    "high level",
    "how does this work",
    "what is this project",
    "what can i ask",
    "onboard",
    "onboarding",
}
HIGH_LEVEL_SOURCE_HINTS = (
    "readme",
    "docs/",
    "manual",
    "architecture",
    "runbooks",
    "user-guide",
    ".md",
)
MANUAL_SOURCE_HINTS = (
    "project_overview.md",
    "architecture_map.md",
    "codebase_manual.md",
    "api_manual.md",
    "architecture_diagram.md",
    "operations_runbook.md",
    "unknowns_and_gaps.md",
    "database_manual.md",
)
LOW_VALUE_PATH_HINTS = (
    ".egg-info/",
    ".egg-info\\",
    "__pycache__/",
    "__pycache__\\",
    ".pytest_cache/",
    ".pytest_cache\\",
    ".ruff_cache/",
    ".ruff_cache\\",
    "build/package/",
    "build/package\\",
)
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt")

RAG_PROMPT_TEMPLATE = """Answer the following question based ONLY on the provided context.
If the context does not contain enough information, say so.
Include citations referencing the source file and line numbers when possible.

Context:
{context}

Question: {question}

Answer:"""


@dataclass
class QueryResult:
    """Result from a retrieval (and optional generation) query."""

    answer: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    retrieved: int = 0
    latency_ms: float = 0.0
    mode: str = "retrieval"  # "retrieval" or "rag"


def is_broad_query(question: str) -> bool:
    """Detect broad/onboarding prompts where docs/manuals should be prioritized."""
    text = question.strip().lower()
    return any(term in text for term in BROAD_QUERY_TERMS)


def extract_file_hints(question: str) -> set[str]:
    """Extract explicit filename hints from question text."""
    matches = re.findall(r"([a-zA-Z0-9_.-]+\.[a-zA-Z0-9_-]+)", question.lower())
    return {m for m in matches if len(m) >= 4}


def is_low_value_source(source: str) -> bool:
    """Return True for generated/cache paths that should be demoted."""
    src = source.lower()
    return any(hint in src for hint in LOW_VALUE_PATH_HINTS)


def is_high_level_source(source: str) -> bool:
    """Identify docs/manual/README style sources suitable for broad summaries."""
    src = source.lower()
    if src.endswith(CODE_SUFFIXES):
        return False
    if src.endswith((".md", ".txt", ".rst", ".adoc")):
        return True
    return any(hint in src for hint in HIGH_LEVEL_SOURCE_HINTS)


def is_manual_source(source: str) -> bool:
    """Return True when source appears to be generated manual content."""
    src = source.lower()
    return any(hint in src for hint in MANUAL_SOURCE_HINTS)


def source_bonus(source: str, *, broad: bool, question_tokens: set[str] | None = None) -> float:
    """Compute source-based rerank bonus for broad architectural queries."""
    src = source.lower()
    bonus = 0.0
    if is_low_value_source(src):
        bonus -= 0.30
    if question_tokens:
        bonus += ownership_bonus_for_source(source, question_tokens=question_tokens)
    if broad and is_manual_source(src):
        bonus += 0.18
    if broad and any(hint in src for hint in HIGH_LEVEL_SOURCE_HINTS):
        bonus += 0.12
    if broad and is_high_level_source(src):
        bonus += 0.10
    if broad and src.endswith("pyproject.toml"):
        bonus -= 0.04
    return bonus


def rerank_query_chunks(
    *,
    question: str,
    chunks: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Rerank and diversify chunk selection for better query answer quality."""
    broad = is_broad_query(question)
    file_hints = extract_file_hints(question)
    question_tokens = tokenize_question(question)
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in chunks:
        similarity = float(chunk.get("similarity", 0.0))
        source = str(chunk.get("source_file", chunk.get("s3_key", "unknown")))
        score = similarity + source_bonus(source, broad=broad, question_tokens=question_tokens)
        if file_hints and any(hint in source.lower() for hint in file_hints):
            score += 0.25
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)

    preferred = [
        (score, chunk)
        for score, chunk in scored
        if not is_low_value_source(str(chunk.get("source_file", chunk.get("s3_key", "unknown"))))
    ]
    ranked_pool = preferred if len(preferred) >= top_k else scored
    ranked_chunks = [chunk for _, chunk in ranked_pool]

    def _chunk_key(chunk: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
        return (
            chunk.get("source_file", chunk.get("s3_key", "unknown")),
            chunk.get("line_start"),
            chunk.get("line_end"),
            chunk.get("chunk_index"),
        )

    def _select_diverse(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        seen_chunks: set[tuple[Any, Any, Any, Any]] = set()
        for chunk in candidates:
            source = str(chunk.get("source_file", chunk.get("s3_key", "unknown"))).lower()
            key = _chunk_key(chunk)
            if source in seen_sources or key in seen_chunks:
                continue
            selected.append(chunk)
            seen_sources.add(source)
            seen_chunks.add(key)
            if len(selected) >= limit:
                return selected
        for chunk in candidates:
            key = _chunk_key(chunk)
            if key in seen_chunks:
                continue
            selected.append(chunk)
            seen_chunks.add(key)
            if len(selected) >= limit:
                break
        return selected

    if not broad:
        return _select_diverse(ranked_chunks, top_k)

    manual_level: list[dict[str, Any]] = []
    high_level: list[dict[str, Any]] = []
    code_level: list[dict[str, Any]] = []
    for chunk in ranked_chunks:
        source = str(chunk.get("source_file", chunk.get("s3_key", "unknown")))
        if is_manual_source(source):
            manual_level.append(chunk)
        elif is_high_level_source(source):
            high_level.append(chunk)
        else:
            code_level.append(chunk)
    if manual_level:
        return _select_diverse(manual_level + high_level + code_level, top_k)
    return _select_diverse(high_level + code_level, top_k)


def retrieve(
    question: str,
    embedding_provider: EmbeddingProvider,
    *,
    collection: str = "default",
    top_k: int = 5,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Embed question and retrieve top-K similar chunks.

    Returns list of chunk dicts with similarity scores.
    """
    s = settings or get_settings()

    conn = get_connection(s)
    try:
        validate_embedding_dimension(conn, embedding_provider.dimension)
        with timed_metric("RagOps", "EmbeddingLatencyMs"):
            query_embedding = embedding_provider.embed([question])[0]
        with timed_metric("RagOps", "QueryLatencyMs"):
            raw_results = search_vectors(
                conn,
                query_embedding,
                collection=collection,
                top_k=max(top_k * 6, top_k),
            )
    finally:
        conn.close()

    return rerank_query_chunks(question=question, chunks=raw_results, top_k=top_k)


# ---------------------------------------------------------------------------
# Lazy RAG: on-demand embedding + two-stage retrieval
# ---------------------------------------------------------------------------


def embed_files_on_demand(
    *,
    collection: str,
    paths: list[str],
    embedding_provider: EmbeddingProvider,
    settings: Settings,
) -> int:
    """Fetch file contents from GitHub and embed them into the collection.

    Only embeds files not already marked as embedded in repo_files.
    Returns the number of newly embedded files.
    """
    from services.core.github_tree import fetch_files_content
    from services.core.storage import (
        compute_sha256,
        get_repo_meta,
        get_unembedded_files,
        mark_files_embedded,
        upsert_chunks,
        upsert_document,
        validate_embedding_dimension,
    )
    from services.ingest.app.chunker import chunk_text, normalize_text

    conn = get_connection(settings)
    try:
        # Get repo metadata (owner, repo, ref) from repo_files table
        meta = get_repo_meta(conn, collection=collection)
        if not meta:
            logger.warning(
                "No repo metadata found for collection %s — skipping on-demand embed",
                collection,
            )
            return 0

        # Find which paths are not yet embedded
        unembedded = get_unembedded_files(conn, collection=collection, paths=paths)
        if not unembedded:
            logger.debug("All %d requested files already embedded for %s", len(paths), collection)
            return 0

        logger.info("Fetching %d unembedded files from GitHub for %s", len(unembedded), collection)

        # Fetch content from GitHub
        token = (settings.github_token or "").strip() or None
        contents = fetch_files_content(
            owner=meta["owner"],
            repo=meta["repo"],
            paths=unembedded,
            ref=meta["ref"],
            token=token,
        )

        if not contents:
            logger.warning("No file contents fetched for %s", collection)
            return 0

        validate_embedding_dimension(conn, embedding_provider.dimension)

        embedded_count = 0
        embedded_paths: list[str] = []

        for file_path, raw_content in contents.items():
            text = normalize_text(raw_content)
            if not text:
                logger.debug("Skipping empty file: %s", file_path)
                continue

            sha = compute_sha256(text)
            chunks = chunk_text(
                text,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
                source_file=file_path,
            )
            if not chunks:
                continue

            chunk_texts = [c.content for c in chunks]
            with timed_metric("RagOps", "EmbeddingLatencyMs"):
                embeddings = embedding_provider.embed(chunk_texts)

            doc_id = upsert_document(
                conn,
                s3_key=file_path,
                sha256=sha,
                collection=collection,
                metadata={"filename": file_path.rsplit("/", 1)[-1], "lazy_embedded": True},
            )

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
            upsert_chunks(conn, doc_id, chunk_records)
            embedded_count += 1
            embedded_paths.append(file_path)
            logger.info("On-demand embedded %s: %d chunks", file_path, len(chunk_records))

        # Mark files as embedded
        if embedded_paths:
            mark_files_embedded(conn, collection=collection, paths=embedded_paths)

        return embedded_count
    finally:
        conn.close()


def retrieve_lazy(
    question: str,
    embedding_provider: EmbeddingProvider,
    *,
    collection: str = "default",
    top_k: int = 5,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Two-stage lazy retrieval.

    Stage 1: Search the {collection}_tree collection for relevant file paths.
    Stage 2: Fetch + embed those files on-demand, then search actual content.

    Falls back to normal retrieval if no tree collection exists.
    """
    s = settings or get_settings()
    tree_collection = f"{collection}_tree"

    # Stage 1: Find relevant file paths from tree embeddings
    conn = get_connection(s)
    try:
        validate_embedding_dimension(conn, embedding_provider.dimension)
        with timed_metric("RagOps", "EmbeddingLatencyMs"):
            query_embedding = embedding_provider.embed([question])[0]

        # Check if tree collection exists by searching it
        tree_results = search_vectors(
            conn,
            query_embedding,
            collection=tree_collection,
            top_k=max(top_k * 3, 15),  # Get more paths for better coverage
        )
    finally:
        conn.close()

    if not tree_results:
        # No tree collection — fall back to normal retrieval
        logger.info("No tree results for %s, falling back to normal retrieval", collection)
        return retrieve(
            question,
            embedding_provider,
            collection=collection,
            top_k=top_k,
            settings=s,
        )

    # Extract file paths from tree results
    relevant_paths = []
    for result in tree_results:
        source = result.get("source_file", "")
        if source:
            relevant_paths.append(source)
    relevant_paths = list(dict.fromkeys(relevant_paths))  # dedupe preserving order

    logger.info(
        "Lazy retrieval found %d relevant file paths for collection %s",
        len(relevant_paths),
        collection,
    )

    # Stage 2: Embed files on-demand
    newly_embedded = embed_files_on_demand(
        collection=collection,
        paths=relevant_paths,
        embedding_provider=embedding_provider,
        settings=s,
    )
    if newly_embedded > 0:
        logger.info("On-demand embedded %d files for %s", newly_embedded, collection)

    # Stage 3: Search the actual content collection
    conn = get_connection(s)
    try:
        with timed_metric("RagOps", "QueryLatencyMs"):
            raw_results = search_vectors(
                conn,
                query_embedding,
                collection=collection,
                top_k=max(top_k * 6, top_k),
            )
    finally:
        conn.close()

    if not raw_results:
        # Fall back to tree results as context (paths only)
        return rerank_query_chunks(question=question, chunks=tree_results, top_k=top_k)

    return rerank_query_chunks(question=question, chunks=raw_results, top_k=top_k)


def query(
    question: str,
    embedding_provider: EmbeddingProvider,
    llm_provider: LLMProvider | None = None,
    *,
    collection: str = "default",
    top_k: int = 5,
    settings: Settings | None = None,
) -> QueryResult:
    """Full query pipeline: retrieve chunks and optionally generate an answer.

    If llm_provider is None, returns retrieval-only results.
    """
    import time

    start = time.perf_counter()
    s = settings or get_settings()

    # Retrieve relevant chunks
    chunks = retrieve(
        question,
        embedding_provider,
        collection=collection,
        top_k=top_k,
        settings=s,
    )

    # Build citations
    citations = [
        {
            "source": c.get("s3_key", c.get("source_file", "unknown")),
            "line_start": c.get("line_start"),
            "line_end": c.get("line_end"),
            "similarity": round(c.get("similarity", 0), 4),
        }
        for c in chunks
    ]

    result = QueryResult(
        retrieved=len(chunks),
        citations=citations,
    )

    if llm_provider and chunks:
        # Build context from chunks
        context_parts = []
        for i, c in enumerate(chunks):
            source = c.get("source_file", c.get("s3_key", "unknown"))
            lines = f"L{c.get('line_start', '?')}-L{c.get('line_end', '?')}"
            context_parts.append(f"[{i + 1}] ({source} {lines}):\n{c['content']}")

        context = "\n\n".join(context_parts)
        prompt = RAG_PROMPT_TEMPLATE.format(context=context, question=question)

        with timed_metric("RagOps", "LLMLatencyMs"):
            result.answer = llm_provider.generate(prompt, max_tokens=1024, temperature=0.1)
        result.mode = "rag"
    else:
        # Retrieval-only mode: return top chunk content as the "answer"
        if chunks:
            result.answer = chunks[0]["content"]
        else:
            result.answer = "No relevant documents found."
        result.mode = "retrieval"

    result.latency_ms = (time.perf_counter() - start) * 1000
    return result
