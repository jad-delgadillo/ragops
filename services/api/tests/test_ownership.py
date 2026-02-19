"""Tests for CODEOWNERS-aware ownership ranking helpers."""

from __future__ import annotations

from pathlib import Path

from services.api.app.ownership import (
    ownership_bonus_for_source,
    ownership_debug_signals_for_source,
    tokenize_question,
)


def _seed_repo_with_codeowners(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "services" / "api" / "app").mkdir(parents=True)
    (root / "services" / "cli").mkdir(parents=True)
    (root / "CODEOWNERS").write_text(
        "/services/api/ @platform-team\n"
        "/services/cli/ @cli-team\n",
        encoding="utf-8",
    )
    api_file = root / "services" / "api" / "app" / "handler.py"
    cli_file = root / "services" / "cli" / "main.py"
    api_file.write_text("def handler():\n    return 200\n", encoding="utf-8")
    cli_file.write_text("def main():\n    return 0\n", encoding="utf-8")
    return api_file, cli_file


def test_ownership_bonus_prefers_matching_area_and_owner_tokens(tmp_path: Path) -> None:
    api_file, cli_file = _seed_repo_with_codeowners(tmp_path)
    q_tokens = tokenize_question("how does platform api flow work?")

    api_bonus = ownership_bonus_for_source(str(api_file), question_tokens=q_tokens)
    cli_bonus = ownership_bonus_for_source(str(cli_file), question_tokens=q_tokens)

    assert api_bonus > 0.0
    assert api_bonus > cli_bonus


def test_ownership_debug_signals_include_match_reasons(tmp_path: Path) -> None:
    api_file, _ = _seed_repo_with_codeowners(tmp_path)
    q_tokens = tokenize_question("platform api ownership")
    bonus, signals = ownership_debug_signals_for_source(str(api_file), question_tokens=q_tokens)
    assert bonus > 0.0
    assert any(s.startswith("ownership_owner_match:") for s in signals)
    assert any(s.startswith("ownership_area_match:") for s in signals)


def test_ownership_bonus_is_zero_without_codeowners(tmp_path: Path) -> None:
    file_path = tmp_path / "repo" / "services" / "api" / "handler.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("def handler():\n    return 200\n", encoding="utf-8")

    q_tokens = tokenize_question("explain api ownership")
    bonus = ownership_bonus_for_source(str(file_path), question_tokens=q_tokens)
    assert bonus == 0.0


def test_ownership_bonus_supports_glob_patterns(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "CODEOWNERS").write_text("*.md @docs-team\n", encoding="utf-8")
    manual = root / "docs" / "guide.md"
    manual.write_text("# Guide\n", encoding="utf-8")

    q_tokens = tokenize_question("show docs team guide")
    bonus = ownership_bonus_for_source(str(manual), question_tokens=q_tokens)
    assert bonus > 0.0
