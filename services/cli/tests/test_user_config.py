"""Tests for user-level config helpers."""

from __future__ import annotations

from pathlib import Path

from services.cli.user_config import load_user_config, save_user_config, user_config_path


def test_user_config_path_uses_provided_home(tmp_path: Path) -> None:
    path = user_config_path(tmp_path)
    assert path == tmp_path / ".ragops" / "config.yaml"


def test_load_user_config_missing_returns_empty(tmp_path: Path) -> None:
    assert load_user_config(tmp_path) == {}


def test_save_user_config_round_trip(tmp_path: Path) -> None:
    save_user_config({"openai_api_key": "k1", "storage_backend": "sqlite"}, tmp_path)
    loaded = load_user_config(tmp_path)
    assert loaded["openai_api_key"] == "k1"
    assert loaded["storage_backend"] == "sqlite"
    assert "updated_at" in loaded

