"""Tests for interactive chat shell helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services.cli.main import (
    _citation_summary,
    _format_chat_provider_label,
    _parse_chat_shell_command,
    _shorten_home,
)


def test_parse_chat_shell_command_variants() -> None:
    assert _parse_chat_shell_command("/help") == ("help", "")
    assert _parse_chat_shell_command("/clear   now") == ("clear", "now")
    assert _parse_chat_shell_command("what is this") == ("", "")


def test_format_chat_provider_label_remote() -> None:
    settings = SimpleNamespace(llm_enabled=True, llm_provider="openai")
    label = _format_chat_provider_label(settings, "https://api.example.com/v1/chat")
    assert label == "remote/api.example.com/v1/chat"


def test_format_chat_provider_label_local() -> None:
    settings = SimpleNamespace(llm_enabled=True, llm_provider="ollama", ollama_llm_model="qwen2.5")
    assert _format_chat_provider_label(settings, None) == "ollama/qwen2.5"


def test_citation_summary_uses_limit() -> None:
    citations = [
        {"source": "/tmp/a.py", "line_start": 1, "line_end": 2},
        {"source": "/tmp/b.py", "line_start": 3, "line_end": 4},
        {"source": "/tmp/c.py", "line_start": 5, "line_end": 6},
        {"source": "/tmp/d.py", "line_start": 7, "line_end": 8},
    ]
    summary = _citation_summary(citations, limit=2)
    assert summary == "a.py:L1-2, b.py:L3-4 (+2 more)"


def test_shorten_home_path(monkeypatch: object) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/Users/tester")))
    assert _shorten_home(Path("/Users/tester/project")) == "~/project"
