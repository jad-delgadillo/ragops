"""Tests for deterministic onboarding manual generation."""

from __future__ import annotations

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


def test_generate_manual_pack_without_db(tmp_path: Path) -> None:
    _seed_project(tmp_path)
    generator = ManualPackGenerator(tmp_path)
    output_dir = tmp_path / "manuals"

    result = generator.generate(output_dir=output_dir, include_db=False)

    assert result.db_status == "skipped"
    assert (output_dir / "CODEBASE_MANUAL.md").exists()
    assert (output_dir / "API_MANUAL.md").exists()
    assert (output_dir / "DATABASE_MANUAL.md").exists()

    db_manual = (output_dir / "DATABASE_MANUAL.md").read_text(encoding="utf-8")
    api_manual = (output_dir / "API_MANUAL.md").read_text(encoding="utf-8")
    assert "Database introspection was skipped" in db_manual
    assert "/v1/query" in api_manual


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
