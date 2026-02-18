"""Query retriever: embed question → vector search → assemble context with citations."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from services.core.config import Settings, get_settings
from services.core.database import get_connection, search_vectors, validate_embedding_dimension
from services.core.logging import timed_metric
from services.core.providers import EmbeddingProvider, LLMProvider

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


def source_bonus(source: str, *, broad: bool) -> float:
    """Compute source-based rerank bonus for broad architectural queries."""
    src = source.lower()
    bonus = 0.0
    if is_low_value_source(src):
        bonus -= 0.30
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
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in chunks:
        similarity = float(chunk.get("similarity", 0.0))
        source = str(chunk.get("source_file", chunk.get("s3_key", "unknown")))
        score = similarity + source_bonus(source, broad=broad)
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

    high_level: list[dict[str, Any]] = []
    code_level: list[dict[str, Any]] = []
    for chunk in ranked_chunks:
        source = str(chunk.get("source_file", chunk.get("s3_key", "unknown")))
        if is_high_level_source(source):
            high_level.append(chunk)
        else:
            code_level.append(chunk)
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
