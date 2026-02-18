"""Tests for retriever reranking and query quality helpers."""

from services.api.app.retriever import (
    extract_file_hints,
    is_broad_query,
    is_low_value_source,
    rerank_query_chunks,
)


def test_is_broad_query_detects_architecture_and_typo() -> None:
    assert is_broad_query("Tell me the architecture")
    assert is_broad_query("can yo tell me about the arquitecture?")


def test_rerank_query_chunks_prioritizes_docs_for_broad_query() -> None:
    chunks = [
        {
            "source_file": "services/cli/main.py",
            "similarity": 0.92,
            "content": "def cmd_chat(...): ...",
        },
        {
            "source_file": "docs/architecture.md",
            "similarity": 0.86,
            "content": "Architecture overview...",
        },
    ]
    ranked = rerank_query_chunks(
        question="can you explain the architecture?",
        chunks=chunks,
        top_k=1,
    )
    assert ranked[0]["source_file"] == "docs/architecture.md"


def test_rerank_query_chunks_diversifies_sources() -> None:
    chunks = [
        {"source_file": "services/cli/main.py", "similarity": 0.91, "content": "A"},
        {"source_file": "services/cli/main.py", "similarity": 0.90, "content": "B"},
        {"source_file": "docs/user-guide.md", "similarity": 0.89, "content": "C"},
    ]
    ranked = rerank_query_chunks(
        question="what is this project overview?",
        chunks=chunks,
        top_k=2,
    )
    sources = [str(row["source_file"]) for row in ranked]
    assert "services/cli/main.py" in sources
    assert "docs/user-guide.md" in sources


def test_extract_file_hints_detects_filename_mentions() -> None:
    hints = extract_file_hints("Tell me about CODEBASE_MANUAL.md and main.py")
    assert "codebase_manual.md" in hints
    assert "main.py" in hints


def test_is_low_value_source_detects_generated_or_cache_paths() -> None:
    assert is_low_value_source("ragops.egg-info/SOURCES.txt")
    assert is_low_value_source("build/package/services/api/app.py")
    assert not is_low_value_source("docs/architecture.md")


def test_rerank_query_chunks_demotes_low_value_sources() -> None:
    chunks = [
        {
            "source_file": "ragops.egg-info/SOURCES.txt",
            "similarity": 0.95,
            "content": "generated source list",
            "chunk_index": 1,
        },
        {
            "source_file": "docs/architecture.md",
            "similarity": 0.82,
            "content": "architecture overview",
            "chunk_index": 2,
        },
    ]
    ranked = rerank_query_chunks(
        question="explain project architecture",
        chunks=chunks,
        top_k=1,
    )
    assert ranked[0]["source_file"] == "docs/architecture.md"


def test_rerank_query_chunks_prefers_explicit_filename_hint() -> None:
    chunks = [
        {
            "source_file": "services/cli/main.py",
            "similarity": 0.90,
            "content": "command handlers",
            "chunk_index": 1,
        },
        {
            "source_file": "manuals/CODEBASE_MANUAL.md",
            "similarity": 0.76,
            "content": "project overview",
            "chunk_index": 2,
        },
    ]
    ranked = rerank_query_chunks(
        question="tell me about CODEBASE_MANUAL.md",
        chunks=chunks,
        top_k=1,
    )
    assert ranked[0]["source_file"] == "manuals/CODEBASE_MANUAL.md"
