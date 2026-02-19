"""Tests for repository helper utilities."""

from pathlib import Path

import pytest

from services.cli.repositories import (
    RepoRecord,
    build_authenticated_clone_url,
    default_repo_name,
    load_repo_registry,
    parse_github_repo_url,
    resolve_collection_pair,
    save_repo_registry,
)


def test_parse_github_repo_url_https() -> None:
    url, owner, repo = parse_github_repo_url("https://github.com/openai/openai-python")
    assert url == "https://github.com/openai/openai-python.git"
    assert owner == "openai"
    assert repo == "openai-python"


def test_parse_github_repo_url_ssh() -> None:
    url, owner, repo = parse_github_repo_url("git@github.com:octocat/Hello-World.git")
    assert url == "https://github.com/octocat/Hello-World.git"
    assert owner == "octocat"
    assert repo == "Hello-World"


def test_default_repo_name() -> None:
    assert default_repo_name("OpenAI", "OpenAI-Python") == "openai-openai-python"


def test_build_authenticated_clone_url() -> None:
    authenticated = build_authenticated_clone_url(
        "https://github.com/openai/openai-python.git",
        "ghp_test_token",
    )
    assert authenticated.startswith("https://x-access-token:")
    assert "@github.com/openai/openai-python.git" in authenticated


def test_resolve_collection_pair_adds_suffixes() -> None:
    code, manuals = resolve_collection_pair(collection="acme-paylink")
    assert code == "acme-paylink_code"
    assert manuals == "acme-paylink_manuals"


def test_resolve_collection_pair_preserves_code_suffix() -> None:
    code, manuals = resolve_collection_pair(collection="acme-paylink_code")
    assert code == "acme-paylink_code"
    assert manuals == "acme-paylink_manuals"


def test_resolve_collection_pair_manual_override() -> None:
    code, manuals = resolve_collection_pair(
        collection="acme-paylink",
        manuals_collection="acme-paylink_docs",
    )
    assert code == "acme-paylink_code"
    assert manuals == "acme-paylink_docs"


def test_repo_registry_round_trip(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()

    original = {
        "openai-openai-python": RepoRecord(
            name="openai-openai-python",
            url="https://github.com/openai/openai-python.git",
            collection="openai-openai-python",
            local_path=str(project_root / ".ragops" / "repos" / "openai-openai-python"),
            ref="main",
            manuals_enabled=True,
            manuals_collection="openai-openai-python_manuals",
            manuals_output=str(project_root / "manuals" / "openai-openai-python"),
            added_at="2026-02-17T00:00:00+00:00",
            last_sync_at="2026-02-17T00:00:00+00:00",
        )
    }
    save_repo_registry(project_root, original)

    loaded = load_repo_registry(project_root)
    assert "openai-openai-python" in loaded
    loaded_record = loaded["openai-openai-python"]
    assert loaded_record.url == original["openai-openai-python"].url
    assert loaded_record.collection == original["openai-openai-python"].collection
    assert loaded_record.manuals_enabled
    assert loaded_record.manuals_collection == "openai-openai-python_manuals"


def test_parse_github_repo_url_empty_raises() -> None:
    with pytest.raises(ValueError, match="required"):
        parse_github_repo_url("")


def test_parse_github_repo_url_non_github_raises() -> None:
    with pytest.raises(ValueError, match="github.com"):
        parse_github_repo_url("https://gitlab.com/org/repo")


def test_parse_github_repo_url_missing_repo_name_raises() -> None:
    with pytest.raises(ValueError, match="owner and repository"):
        parse_github_repo_url("https://github.com/only-owner")

