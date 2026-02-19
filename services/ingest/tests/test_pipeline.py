"""Tests for ingest pipeline file collection behavior."""

from pathlib import Path

from services.ingest.app.pipeline import collect_ingest_files


def test_collect_ingest_files_allows_target_inside_dot_ragops(tmp_path: Path) -> None:
    target = tmp_path / ".ragops" / "repos" / "sample-repo"
    target.mkdir(parents=True)
    app_file = target / "app.py"
    app_file.write_text("print('ok')\n")

    files = collect_ingest_files(target)
    assert app_file in files


def test_collect_ingest_files_ignores_nested_git_and_node_modules(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    (target / "src").mkdir(parents=True)
    (target / ".git").mkdir(parents=True)
    (target / "node_modules").mkdir(parents=True)

    good = target / "src" / "main.py"
    bad_git = target / ".git" / "config.py"
    bad_nm = target / "node_modules" / "index.js"

    good.write_text("print('ok')\n")
    bad_git.write_text("print('skip')\n")
    bad_nm.write_text("console.log('skip')\n")

    files = collect_ingest_files(target)
    assert good in files
    assert bad_git not in files
    assert bad_nm not in files


def test_collect_ingest_files_ignores_egg_info_suffix_dirs(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    (target / "ragops.egg-info").mkdir(parents=True)
    (target / "src").mkdir(parents=True)
    bad = target / "ragops.egg-info" / "SOURCES.txt"
    good = target / "src" / "main.py"
    bad.write_text("ignored\n")
    good.write_text("print('ok')\n")

    files = collect_ingest_files(target)
    assert good in files
    assert bad not in files


def test_collect_ingest_files_honors_extra_ignore_dirs(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    (target / "manuals").mkdir(parents=True)
    (target / "docs").mkdir(parents=True)
    bad = target / "manuals" / "CODEBASE_MANUAL.md"
    good = target / "docs" / "user-guide.md"
    bad.write_text("manual\n")
    good.write_text("guide\n")

    files = collect_ingest_files(target, extra_ignore_dirs={"manuals"})
    assert good in files
    assert bad not in files


def test_collect_ingest_files_can_limit_to_include_paths(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    (target / "src").mkdir(parents=True)
    (target / "docs").mkdir(parents=True)
    keep = target / "src" / "main.py"
    drop = target / "docs" / "guide.md"
    keep.write_text("print('ok')\n")
    drop.write_text("guide\n")

    files = collect_ingest_files(target, include_paths={"src/main.py"})
    assert keep in files
    assert drop not in files


def test_collect_ingest_files_empty_include_paths_returns_none(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    (target / "src").mkdir(parents=True)
    keep = target / "src" / "main.py"
    keep.write_text("print('ok')\n")

    files = collect_ingest_files(target, include_paths=set())
    assert files == []
