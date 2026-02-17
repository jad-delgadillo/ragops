"""Query retriever: embed question → vector search → assemble context with citations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from services.core.config import Settings, get_settings
from services.core.database import get_connection, search_vectors, validate_embedding_dimension
from services.core.logging import timed_metric
from services.core.providers import EmbeddingProvider, LLMProvider

logger = logging.getLogger(__name__)

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
            results = search_vectors(conn, query_embedding, collection=collection, top_k=top_k)
    finally:
        conn.close()

    return results


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
