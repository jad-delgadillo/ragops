"""Tests for `ragops config` command handlers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.cli.main import cmd_config_doctor, cmd_config_set, cmd_config_show


def test_cmd_config_set_and_show_json(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    set_args = argparse.Namespace(
        openai_api_key="sk-test-123456",
        unset_openai_api_key=False,
        llm_enabled="true",
        storage_backend="sqlite",
        local_db_path=".ragops/ragops.db",
        json=True,
    )
    cmd_config_set(set_args)
    set_out = capsys.readouterr().out
    set_payload = json.loads(set_out)
    assert set_payload["status"] == "ok"

    show_args = argparse.Namespace(reveal_secrets=False, json=True)
    cmd_config_show(show_args)
    show_out = capsys.readouterr().out
    show_payload = json.loads(show_out)
    config = show_payload["config"]
    assert config["openai_api_key"].startswith("sk-")
    assert "..." in config["openai_api_key"]
    assert config["storage_backend"] == "sqlite"


def test_cmd_config_show_empty_json(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    show_args = argparse.Namespace(reveal_secrets=False, json=True)
    cmd_config_show(show_args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["config"] == {}


def test_cmd_config_doctor_json_reports_effective_state(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        "[project]\nname='doctor-demo'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    (project / ".env").write_text(
        "STORAGE_BACKEND=sqlite\nLOCAL_DB_PATH=.ragops/doctor.db\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(project)

    doctor_args = argparse.Namespace(json=True, fix=False)
    cmd_config_doctor(doctor_args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] in {"ok", "warn"}
    assert payload["effective"]["storage_backend"] == "sqlite"
    assert payload["effective"]["local_db_path"] == ".ragops/doctor.db"
    assert any(check["name"] == "storage_health" for check in payload["checks"])
    assert payload["fix"]["requested"] is False


def test_cmd_config_doctor_fix_writes_missing_project_env(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    project = tmp_path / "proj-fix"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        "[project]\nname='doctor-fix-demo'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    (project / ".env").write_text("", encoding="utf-8")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(project)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("LOCAL_DB_PATH", raising=False)
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    # Seed global config for key fallback.
    set_args = argparse.Namespace(
        openai_api_key="sk-global-112233",
        unset_openai_api_key=False,
        llm_enabled="true",
        storage_backend="sqlite",
        local_db_path=".ragops/global.db",
        json=True,
    )
    cmd_config_set(set_args)
    capsys.readouterr()

    doctor_args = argparse.Namespace(json=True, fix=True)
    cmd_config_doctor(doctor_args)
    payload = json.loads(capsys.readouterr().out)

    env_content = (project / ".env").read_text(encoding="utf-8")
    assert "STORAGE_BACKEND=sqlite" in env_content
    assert "LOCAL_DB_PATH=.ragops/global.db" in env_content
    assert "LLM_ENABLED=true" in env_content
    assert "OPENAI_API_KEY=sk-global-112233" in env_content
    assert payload["fix"]["requested"] is True
    assert any(item.startswith("STORAGE_BACKEND=") for item in payload["fix"]["applied"])
