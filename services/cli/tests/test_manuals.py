"""Tests for deterministic onboarding manual generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.cli.docgen.manuals import ManualPackGenerator
from services.core.config import Settings


def _seed_project(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    (root / "services" / "api" / "app").mkdir(parents=True)
    (root / "services" / "ingest" / "app").mkdir(parents=True)
    (root / "services" / "api" / "app" / "handler.py").write_text(
        "def lambda_handler(event, context):\n    return {'statusCode': 200}\n",
        encoding="utf-8",
    )
    (root / "services" / "ingest" / "app" / "handler.py").write_text(
        "def lambda_handler(event, context):\n    return {'statusCode': 200}\n",
        encoding="utf-8",
    )


def _seed_lazy_rag_shape(root: Path) -> None:
    _seed_project(root)
    (root / "services" / "api" / "app" / "repo_onboarding.py").write_text(
        "def onboard_github_repo_lazy():\n    return {}\n",
        encoding="utf-8",
    )
    (root / "services" / "api" / "app" / "retriever.py").write_text(
        "def retrieve_lazy():\n    return []\n",
        encoding="utf-8",
    )
    (root / "services" / "core").mkdir(parents=True, exist_ok=True)
    (root / "services" / "core" / "github_tree.py").write_text(
        "def fetch_file_tree():\n    return []\n",
        encoding="utf-8",
    )
    (root / "services" / "core" / "database.py").write_text(
        "def get_connection():\n    return None\n",
        encoding="utf-8",
    )
    (root / "services" / "core" / "openai_provider.py").write_text(
        "class OpenAIProvider:\n    pass\n",
        encoding="utf-8",
    )
    (root / "services" / "core" / "schema.sql").write_text(
        "-- schema\n",
        encoding="utf-8",
    )


def test_generate_manual_pack_without_db(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    generator = ManualPackGenerator(tmp_path)
    output_dir = tmp_path / "manuals"

    result = generator.generate(output_dir=output_dir, include_db=False)

    assert result.db_status == "skipped"
    assert (output_dir / "CODEBASE_MANUAL.md").exists()
    assert (output_dir / "API_MANUAL.md").exists()
    assert (output_dir / "PROJECT_OVERVIEW.md").exists()
    assert (output_dir / "ARCHITECTURE_MAP.md").exists()
    assert (output_dir / "ARCHITECTURE_DIAGRAM.md").exists()
    assert (output_dir / "OPERATIONS_RUNBOOK.md").exists()
    assert (output_dir / "UNKNOWNS_AND_GAPS.md").exists()
    assert (output_dir / "DATABASE_MANUAL.md").exists()
    assert (output_dir / "SCAN_INDEX.json").exists()

    db_manual = (output_dir / "DATABASE_MANUAL.md").read_text(encoding="utf-8")
    api_manual = (output_dir / "API_MANUAL.md").read_text(encoding="utf-8")
    architecture_manual = (output_dir / "ARCHITECTURE_DIAGRAM.md").read_text(encoding="utf-8")
    project_overview = (output_dir / "PROJECT_OVERVIEW.md").read_text(encoding="utf-8")
    scan_index = json.loads((output_dir / "SCAN_INDEX.json").read_text(encoding="utf-8"))
    assert "Database introspection was skipped" in db_manual
    assert "/v1/query" in api_manual
    assert "Key Entrypoints" in project_overview
    assert "PROJECT_OVERVIEW.md" in scan_index["manuals"]
    assert "```mermaid" in architecture_manual
    assert "sequenceDiagram" in architecture_manual
    assert "Project Scan" in architecture_manual


def test_generate_manual_pack_renders_lazy_repo_flow(tmp_path: Path) -> None:
    _seed_lazy_rag_shape(tmp_path)
    generator = ManualPackGenerator(tmp_path)
    output_dir = tmp_path / "manuals"

    generator.generate(output_dir=output_dir, include_db=False)

    architecture_manual = (output_dir / "ARCHITECTURE_DIAGRAM.md").read_text(encoding="utf-8")
    assert "Lazy Repo Onboarding + On-demand Retrieval" in architecture_manual
    assert "ragops repo add-lazy <url>" in architecture_manual
    assert "Search {collection}_tree for relevant paths" in architecture_manual


def test_generate_manual_pack_requires_settings_for_db(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    generator = ManualPackGenerator(tmp_path)

    with pytest.raises(ValueError):
        generator.generate(output_dir=tmp_path / "manuals", include_db=True, settings=None)


def test_generate_manual_pack_with_db_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_project(tmp_path)
    generator = ManualPackGenerator(tmp_path)
    output_dir = tmp_path / "manuals"
    settings = Settings(_env_file=None, OPENAI_API_KEY="test")

    def _fake_collect_database_snapshot(_: Settings) -> tuple[None, str]:
        return None, "db unavailable in test"

    monkeypatch.setattr(generator, "_collect_database_snapshot", _fake_collect_database_snapshot)
    result = generator.generate(output_dir=output_dir, include_db=True, settings=settings)

    assert result.db_status == "degraded"
    assert result.db_error == "db unavailable in test"
    db_manual = (output_dir / "DATABASE_MANUAL.md").read_text(encoding="utf-8")
    assert "Database introspection failed" in db_manual
