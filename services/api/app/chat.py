"""Conversational RAG: multi-turn chat with DB-backed session memory."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from uuid import uuid4

from services.core.config import Settings, get_settings
from services.core.database import (
    count_chat_turns,
    ensure_chat_tables,
    get_connection,
    insert_chat_message,
    list_chat_messages,
    search_vectors,
    upsert_chat_session,
    validate_embedding_dimension,
)
from services.core.logging import timed_metric
from services.core.providers import EmbeddingProvider, LLMProvider

CHAT_MODES = {
    "default",
    "explain_like_junior",
    "show_where_in_code",
    "step_by_step",
}
ANSWER_STYLES = {"concise", "detailed"}
ONBOARDING_TERMS = {
    "overview",
    "start",
    "begin",
    "onboard",
    "onboarding",
    "architecture",
    "project",
    "codebase",
    "how does this work",
    "what is this",
}
PRIORITY_PATH_HINTS = (
    "readme",
    "architecture.md",
    "docs/",
    "user-guide",
    "runbooks",
    "codebase_manual.md",
    "api_manual.md",
    "database_manual.md",
    "services/cli/main.py",
)
HIGH_LEVEL_PATH_HINTS = (
    "readme",
    "docs/",
    "manual",
    "user-guide",
    "runbooks",
    "architecture",
    ".md",
)
CODE_DUMP_MARKERS = (
    "def ",
    "class ",
    "import ",
    "from ",
    "return ",
    "if ",
    "for ",
    "while ",
    "try:",
    "except",
    "dependencies = [",
    "[project]",
)
HISTORY_MESSAGE_MAX_CHARS = 700

MODE_INSTRUCTIONS = {
    "default": "Be concise, technically accurate, and grounded in context.",
    "explain_like_junior": (
        "Explain like a junior engineer onboarding to a new codebase. "
        "Define key terms and avoid skipping foundational steps."
    ),
    "show_where_in_code": (
        "Focus on where behavior lives in the code and cite files/lines clearly. "
        "Use direct references to code locations when possible."
    ),
    "step_by_step": (
        "Return the answer as a numbered sequence of concrete steps, "
        "each mapped to retrieved context."
    ),
}
STYLE_INSTRUCTIONS = {
    "concise": (
        "Return 3-6 short bullets. Start with a one-sentence summary, "
        "then key points and where to read next."
    ),
    "detailed": (
        "Return a structured explanation with sections and actionable detail. "
        "Still avoid dumping long raw file blocks."
    ),
}

CHAT_PROMPT_TEMPLATE = """You are an internal codebase onboarding assistant.
Answer ONLY from the provided context snippets and conversation history.
If the answer is not in the context, reply exactly:
I don't know based on indexed project context.

Mode instruction:
{mode_instruction}

Answer style instruction:
{style_instruction}

Output rules:
- Start with a direct summary.
- Cite the most relevant files/lines.
- Do NOT paste large raw config/file blocks unless the user explicitly asks.
- If uncertain, say you are uncertain based on indexed context.

Conversation history:
{history}

Retrieved context:
{context}

User question:
{question}

Answer:
"""


@dataclass
class ChatResult:
    """Result from chat endpoint."""

    session_id: str
    answer: str = ""
    citations: list[dict[str, object]] = field(default_factory=list)
    retrieved: int = 0
    latency_ms: float = 0.0
    mode: str = "default"
    turn_index: int = 0
    answer_style: str = "concise"
    context_snippets: list[dict[str, object]] = field(default_factory=list)


def normalize_chat_mode(mode: str | None) -> str:
    """Normalize and validate chat mode."""
    normalized = (mode or "default").strip().lower()
    if normalized not in CHAT_MODES:
        supported = ", ".join(sorted(CHAT_MODES))
        raise ValueError(f"Unsupported mode '{mode}'. Supported modes: {supported}")
    return normalized


def normalize_answer_style(answer_style: str | None) -> str:
    """Normalize and validate answer style."""
    normalized = (answer_style or "concise").strip().lower()
    if normalized not in ANSWER_STYLES:
        supported = ", ".join(sorted(ANSWER_STYLES))
        raise ValueError(
            f"Unsupported answer_style '{answer_style}'. Supported values: {supported}"
        )
    return normalized


def render_history(messages: list[dict[str, object]]) -> str:
    """Render messages into compact plain-text transcript."""
    if not messages:
        return "(no prior conversation)"
    lines: list[str] = []
    for msg in messages:
        role = str(msg.get("role", "user")).lower()
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        if len(content) > HISTORY_MESSAGE_MAX_CHARS:
            content = content[:HISTORY_MESSAGE_MAX_CHARS].rstrip() + "..."
        if role == "assistant" and looks_like_code_dump(content):
            content = "[previous assistant response omitted: raw code/config dump]"
        speaker = "User" if role == "user" else "Assistant"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines) if lines else "(no prior conversation)"


def build_mode_instruction(mode: str) -> str:
    """Return instruction snippet for requested mode."""
    return MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["default"])


def build_style_instruction(answer_style: str) -> str:
    """Return style instruction snippet."""
    return STYLE_INSTRUCTIONS.get(answer_style, STYLE_INSTRUCTIONS["concise"])


def is_onboarding_question(question: str) -> bool:
    """Detect broad onboarding prompts where docs/README should be prioritized."""
    text = question.lower()
    return any(token in text for token in ONBOARDING_TERMS)


def source_bonus(source: str, *, broad_onboarding: bool) -> float:
    """Compute source-based rerank bonus for onboarding questions."""
    src = source.lower()
    bonus = 0.0
    if broad_onboarding:
        if any(hint in src for hint in PRIORITY_PATH_HINTS):
            bonus += 0.12
        if is_high_level_source(src):
            bonus += 0.10
        if src.endswith("pyproject.toml"):
            bonus -= 0.04
    return bonus


def is_high_level_source(source: str) -> bool:
    """Identify docs/manual/README style sources suitable for onboarding summaries."""
    src = source.lower()
    if src.endswith((".py", ".ts", ".tsx", ".js", ".java", ".go", ".rs")):
        return False
    if src.endswith((".md", ".txt", ".rst", ".adoc")):
        return True
    return any(hint in src for hint in HIGH_LEVEL_PATH_HINTS)


def rerank_chunks(
    question: str,
    chunks: list[dict[str, object]],
    top_k: int,
) -> list[dict[str, object]]:
    """Rerank raw vector results with lightweight onboarding-aware source priors."""
    broad = is_onboarding_question(question)
    scored: list[tuple[float, dict[str, object]]] = []
    for chunk in chunks:
        similarity = float(chunk.get("similarity", 0.0))
        source = str(chunk.get("source_file", chunk.get("s3_key", "unknown")))
        score = similarity + source_bonus(source, broad_onboarding=broad)
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not broad:
        return [chunk for _, chunk in scored[:top_k]]

    high_level = []
    code_level = []
    for _, chunk in scored:
        source = str(chunk.get("source_file", chunk.get("s3_key", "unknown")))
        if is_high_level_source(source):
            high_level.append(chunk)
        else:
            code_level.append(chunk)

    selected = high_level[:top_k]
    if len(selected) < top_k:
        selected.extend(code_level[: top_k - len(selected)])
    return selected


def build_context_snippets(
    chunks: list[dict[str, object]],
    *,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Build trimmed context snippets for UI inspection and debugging."""
    snippets: list[dict[str, object]] = []
    for chunk in chunks[:limit]:
        content = str(chunk.get("content", "")).strip()
        excerpt = content[:420] + ("..." if len(content) > 420 else "")
        snippets.append(
            {
                "source": str(chunk.get("source_file", chunk.get("s3_key", "unknown"))),
                "line_start": chunk.get("line_start"),
                "line_end": chunk.get("line_end"),
                "similarity": round(float(chunk.get("similarity", 0.0)), 4),
                "content": excerpt,
            }
        )
    return snippets


def trim_context_content(content: str, *, limit: int) -> str:
    """Trim context content before prompt injection to reduce model code dumping."""
    text = content.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n..."


def build_prompt_context(
    chunks: list[dict[str, object]],
    *,
    question: str,
    answer_style: str,
) -> str:
    """Format and trim retrieved chunks for the model prompt."""
    broad = is_onboarding_question(question)
    lines: list[str] = []
    for i, chunk in enumerate(chunks):
        source = str(chunk.get("source_file", chunk.get("s3_key", "unknown")))
        line_span = f"L{chunk.get('line_start', '?')}-L{chunk.get('line_end', '?')}"
        default_limit = 1600 if answer_style == "detailed" else 1000
        code_limit = 900 if answer_style == "detailed" else 550
        limit = code_limit if broad and not is_high_level_source(source) else default_limit
        content = trim_context_content(str(chunk.get("content", "")), limit=limit)
        lines.append(f"[{i + 1}] ({source} {line_span}):\n{content}")
    return "\n\n".join(lines)


def looks_like_code_dump(answer: str) -> bool:
    """Detect low-quality model output that is mostly raw code/config text."""
    text = answer.strip()
    if not text:
        return False
    normalized = text.lower()
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= 3:
        return False
    marker_hits = sum(normalized.count(marker) for marker in CODE_DUMP_MARKERS)
    code_punct = sum(text.count(ch) for ch in "{}[]();`")
    has_long_indented_block = any(line.startswith("    ") for line in lines[:20])
    likely_code = marker_hits >= 4 or (marker_hits >= 2 and has_long_indented_block)
    strong_structure = code_punct >= 4 or has_long_indented_block
    return bool(likely_code and strong_structure)


def finalize_answer(
    *,
    generated_answer: str,
    question: str,
    chunks: list[dict[str, object]],
    mode: str,
    answer_style: str,
) -> str:
    """Normalize generated answer and downgrade to fallback if quality is poor."""
    cleaned = generated_answer.strip()
    if not cleaned:
        return build_retrieval_fallback(
            question=question,
            chunks=chunks,
            mode=mode,
            answer_style=answer_style,
        )
    if looks_like_code_dump(cleaned):
        return build_retrieval_fallback(
            question=question,
            chunks=chunks,
            mode=mode,
            answer_style=answer_style,
        )
    return cleaned


def build_retrieval_fallback(
    *,
    question: str,
    chunks: list[dict[str, object]],
    mode: str,
    answer_style: str,
) -> str:
    """Generate a compact retrieval-only answer when LLM is disabled."""
    if not chunks:
        return "I don't know based on indexed project context."

    snippets = build_context_snippets(chunks, limit=5 if answer_style == "detailed" else 3)
    lines: list[str] = []
    if mode == "step_by_step":
        lines.append("1. Relevant indexed evidence for your question:")
        for idx, snip in enumerate(snippets, start=2):
            source = snip["source"]
            start = snip.get("line_start", "?")
            end = snip.get("line_end", "?")
            lines.append(f"{idx}. `{source}` (L{start}-L{end})")
    else:
        lines.append("Summary: I found relevant project context in these sources.")
        for snip in snippets:
            source = snip["source"]
            start = snip.get("line_start", "?")
            end = snip.get("line_end", "?")
            lines.append(f"- `{source}` (L{start}-L{end})")

    if answer_style == "detailed":
        lines.append("")
        lines.append("Key extracted lines:")
        for snip in snippets[:3]:
            preview = str(snip["content"]).replace("\n", " ")
            lines.append(f"- {preview}")
    else:
        lines.append("")
        lines.append("Ask a follow-up like: 'summarize this in plain English'.")

    return "\n".join(lines)


def chat(
    question: str,
    embedding_provider: EmbeddingProvider,
    llm_provider: LLMProvider | None = None,
    *,
    session_id: str | None = None,
    mode: str = "default",
    answer_style: str = "concise",
    collection: str = "default",
    top_k: int = 5,
    settings: Settings | None = None,
) -> ChatResult:
    """Execute conversational RAG with persisted memory."""
    s = settings or get_settings()
    start = time.perf_counter()
    selected_mode = normalize_chat_mode(mode)
    selected_answer_style = normalize_answer_style(answer_style)
    active_session_id = session_id or str(uuid4())

    conn = get_connection(s)
    try:
        ensure_chat_tables(conn)
        validate_embedding_dimension(conn, embedding_provider.dimension)
        upsert_chat_session(
            conn,
            session_id=active_session_id,
            collection=collection,
            mode=selected_mode,
        )
        history = list_chat_messages(
            conn,
            session_id=active_session_id,
            limit=max(1, s.chat_history_turns * 2),
        )

        insert_chat_message(
            conn,
            session_id=active_session_id,
            role="user",
            content=question,
            metadata={
                "collection": collection,
                "mode": selected_mode,
                "answer_style": selected_answer_style,
            },
        )

        with timed_metric("RagOps", "EmbeddingLatencyMs"):
            query_embedding = embedding_provider.embed([question])[0]
        with timed_metric("RagOps", "QueryLatencyMs"):
            raw_chunks = search_vectors(
                conn,
                query_embedding,
                collection=collection,
                top_k=max(top_k * 2, top_k),
            )
        chunks = rerank_chunks(question, raw_chunks, top_k=top_k)
        context_snippets = build_context_snippets(chunks, limit=min(max(top_k, 1), 8))

        citations = [
            {
                "source": c.get("s3_key", c.get("source_file", "unknown")),
                "line_start": c.get("line_start"),
                "line_end": c.get("line_end"),
                "similarity": round(float(c.get("similarity", 0.0)), 4),
            }
            for c in chunks
        ]

        if llm_provider and chunks:
            prompt = CHAT_PROMPT_TEMPLATE.format(
                mode_instruction=build_mode_instruction(selected_mode),
                style_instruction=build_style_instruction(selected_answer_style),
                history=render_history(history),
                context=build_prompt_context(
                    chunks,
                    question=question,
                    answer_style=selected_answer_style,
                ),
                question=question,
            )
            with timed_metric("RagOps", "LLMLatencyMs"):
                generated = llm_provider.generate(prompt, max_tokens=1024, temperature=0.1)
            answer = finalize_answer(
                generated_answer=generated,
                question=question,
                chunks=chunks,
                mode=selected_mode,
                answer_style=selected_answer_style,
            )
        else:
            answer = build_retrieval_fallback(
                question=question,
                chunks=chunks,
                mode=selected_mode,
                answer_style=selected_answer_style,
            )

        insert_chat_message(
            conn,
            session_id=active_session_id,
            role="assistant",
            content=answer,
            citations=citations,
            metadata={
                "collection": collection,
                "mode": selected_mode,
                "answer_style": selected_answer_style,
            },
        )
        turn_index = count_chat_turns(conn, session_id=active_session_id)
    finally:
        conn.close()

    return ChatResult(
        session_id=active_session_id,
        answer=answer,
        citations=citations,
        retrieved=len(citations),
        latency_ms=(time.perf_counter() - start) * 1000,
        mode=selected_mode,
        turn_index=turn_index,
        answer_style=selected_answer_style,
        context_snippets=context_snippets if chunks else [],
    )
