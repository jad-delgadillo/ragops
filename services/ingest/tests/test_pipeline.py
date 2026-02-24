"""Tests for ingest pipeline file collection behavior."""

from pathlib import Path

from services.core.config import Settings
from services.core.providers import EmbeddingProvider
from services.ingest.app.pipeline import collect_ingest_files, ingest_local_directory


class _DummyEmbeddingProvider(EmbeddingProvider):
    PROVIDER = "dummy"
    MODEL = "dummy-embed-1"

    @property
    def dimension(self) -> int:
        return 3

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, float(i), 0.5] for i, _ in enumerate(texts, start=1)]


def _sqlite_settings(db_path: Path, *, chunk_size: int, chunk_overlap: int) -> Settings:
    return Settings(
        _env_file=None,
        OPENAI_API_KEY="test",
        STORAGE_BACKEND="sqlite",
        LOCAL_DB_PATH=str(db_path),
        DATABASE_URL="",
        NEON_CONNECTION_STRING="",
        ENVIRONMENT="local",
        CHUNK_SIZE=chunk_size,
        CHUNK_OVERLAP=chunk_overlap,
    )


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


def test_ingest_reindexes_when_index_version_changes(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    target = project / "main.py"
    target.write_text("print('hello world')\n")

    db_path = tmp_path / "ragops.db"
    provider = _DummyEmbeddingProvider()
    settings_v1 = _sqlite_settings(db_path, chunk_size=256, chunk_overlap=32)
    settings_v2 = _sqlite_settings(db_path, chunk_size=128, chunk_overlap=16)

    first = ingest_local_directory(
        project,
        embedding_provider=provider,
        collection="demo",
        settings=settings_v1,
    )
    second = ingest_local_directory(
        project,
        embedding_provider=provider,
        collection="demo",
        settings=settings_v1,
    )
    third = ingest_local_directory(
        project,
        embedding_provider=provider,
        collection="demo",
        settings=settings_v2,
    )

    assert first.indexed_docs == 1
    assert first.skipped_docs == 0
    assert second.indexed_docs == 0
    assert second.skipped_docs == 1
    assert third.indexed_docs == 1
    assert third.skipped_docs == 0
