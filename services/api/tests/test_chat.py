"""Tests for chat mode validation and API handler behavior."""

from __future__ import annotations

import json
from typing import Any

import pytest

from services.api.app.chat import (
    ChatResult,
    finalize_answer,
    looks_like_code_dump,
    normalize_answer_style,
    normalize_chat_mode,
    render_history,
    rerank_chunks,
)
from services.api.app.handler import _handle_chat, _handle_feedback
from services.core.config import Settings


def test_normalize_chat_mode_accepts_supported_values() -> None:
    assert normalize_chat_mode("default") == "default"
    assert normalize_chat_mode("explain_like_junior") == "explain_like_junior"
    assert normalize_chat_mode("show_where_in_code") == "show_where_in_code"
    assert normalize_chat_mode("step_by_step") == "step_by_step"


def test_normalize_chat_mode_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        normalize_chat_mode("invalid-mode")


def test_normalize_answer_style_values() -> None:
    assert normalize_answer_style("concise") == "concise"
    assert normalize_answer_style("detailed") == "detailed"
    with pytest.raises(ValueError):
        normalize_answer_style("verbose")


def test_render_history_compacts_messages() -> None:
    text = render_history(
        [
            {"role": "user", "content": "How do I start?"},
            {"role": "assistant", "content": "Read services/cli/main.py first."},
        ]
    )
    assert "User: How do I start?" in text
    assert "Assistant: Read services/cli/main.py first." in text


def test_render_history_omits_code_dump_assistant_messages() -> None:
    text = render_history(
        [
            {"role": "user", "content": "what is this project?"},
            {
                "role": "assistant",
                "content": (
                    "def _render_api_manual(self, snapshot):\n"
                    "    api_rows = snapshot.get('api', [])\n"
                    "    if not api_rows:\n"
                    "        return ''"
                ),
            },
        ]
    )
    assert "omitted: raw code/config dump" in text


def test_looks_like_code_dump_detects_raw_source() -> None:
    raw = """
def _render_api_manual(self, snapshot):
    api_rows = snapshot.get("api", [])
    cli_rows = snapshot.get("cli", [])
    api_table = "\\n".join(...)
    if not api_table:
        api_table = "| - | - | No API endpoints discovered | - |"
"""
    assert looks_like_code_dump(raw)


def test_looks_like_code_dump_ignores_clean_summary() -> None:
    answer = (
        "RAG Ops is a codebase Q&A platform.\n"
        "- It ingests repo files into vectors.\n"
        "- It answers with citations and feedback capture."
    )
    assert not looks_like_code_dump(answer)


def test_finalize_answer_falls_back_when_model_dumps_code() -> None:
    chunks = [
        {
            "source_file": "README.md",
            "line_start": 1,
            "line_end": 30,
            "similarity": 0.9,
            "content": "RAG Ops helps teams query codebases with citations.",
        }
    ]
    answer = finalize_answer(
        generated_answer=(
            "def foo():\n    return bar\nclass X:\n    pass\nimport os\nfrom x import y"
        ),
        question="what is this project about?",
        chunks=chunks,
        mode="default",
        answer_style="concise",
    )
    assert answer.startswith("Summary:")
    assert "README.md" in answer


def test_rerank_chunks_prioritizes_docs_for_broad_onboarding_questions() -> None:
    chunks = [
        {
            "source_file": "services/cli/docgen/manuals.py",
            "similarity": 0.95,
            "content": "def _render_api_manual(...): ...",
        },
        {
            "source_file": "README.md",
            "similarity": 0.90,
            "content": "RAG Ops lets teams query codebases with AI.",
        },
    ]
    ranked = rerank_chunks("what is this project about?", chunks, top_k=1)
    assert ranked[0]["source_file"] == "README.md"


def test_handle_chat_returns_400_for_invalid_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, OPENAI_API_KEY="test")
    monkeypatch.setattr("services.api.app.handler.get_settings", lambda: settings)

    event = {
        "body": json.dumps(
            {
                "question": "How does this work?",
                "collection": "default",
                "mode": "invalid",
            }
        )
    }
    # Isolate from local .env
    response = _handle_chat(event)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "Unsupported mode" in body["error"]


def test_handle_chat_returns_400_for_invalid_answer_style(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, OPENAI_API_KEY="test")
    monkeypatch.setattr("services.api.app.handler.get_settings", lambda: settings)
    event = {
        "body": json.dumps(
            {
                "question": "How does this work?",
                "collection": "default",
                "answer_style": "verbose",
            }
        )
    }
    response = _handle_chat(event)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "Unsupported answer_style" in body["error"]


def test_handle_chat_success_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, OPENAI_API_KEY="test")

    class _EmbedProvider:
        dimension = 1536

    def _fake_chat(*args, **kwargs):  # type: ignore[no-untyped-def]
        return ChatResult(
            session_id="session-1",
            answer="Use ragops ingest, then ragops query.",
            citations=[{"source": "README.md", "line_start": 1, "line_end": 30, "similarity": 0.9}],
            retrieved=1,
            latency_ms=123.4,
            mode="default",
            turn_index=2,
        )

    monkeypatch.setattr("services.api.app.handler.get_settings", lambda: settings)
    monkeypatch.setattr(
        "services.api.app.handler.get_embedding_provider",
        lambda _: _EmbedProvider(),
    )
    monkeypatch.setattr("services.api.app.handler.get_llm_provider", lambda _: None)
    monkeypatch.setattr("services.api.app.handler.chat", _fake_chat)

    event = {"body": json.dumps({"question": "What should I run first?"})}
    response = _handle_chat(event)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["session_id"] == "session-1"
    assert body["turn_index"] == 2
    assert "answer" in body
    assert body["answer_style"] == "concise"


def test_handle_feedback_rejects_bad_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, OPENAI_API_KEY="test")
    monkeypatch.setattr("services.api.app.handler.get_settings", lambda: settings)
    event = {"body": json.dumps({"verdict": "meh"})}
    response = _handle_feedback(event)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "must be 'positive' or 'negative'" in body["error"]


def test_handle_feedback_success_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, OPENAI_API_KEY="test")

    class _DummyConn:
        def close(self) -> None:
            return None

    def _fake_insert_feedback(conn: Any, **kwargs: Any) -> int:
        return 99

    monkeypatch.setattr("services.api.app.handler.get_settings", lambda: settings)
    monkeypatch.setattr("services.api.app.handler.get_connection", lambda _: _DummyConn())
    monkeypatch.setattr("services.api.app.handler.ensure_feedback_table", lambda _: None)
    monkeypatch.setattr("services.api.app.handler.insert_feedback", _fake_insert_feedback)

    event = {"body": json.dumps({"verdict": "positive", "collection": "default"})}
    response = _handle_feedback(event)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "ok"
    assert body["feedback_id"] == 99
