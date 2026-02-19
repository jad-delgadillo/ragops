"""Parser coverage for CLI UX-focused command options."""

from __future__ import annotations

from services.cli.main import build_parser


def test_chat_parser_allows_interactive_mode_without_question() -> None:
    parser = build_parser()
    args = parser.parse_args(["chat"])
    assert args.command == "chat"
    assert args.question is None
    assert args.show_ranking_signals is False


def test_scan_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["scan"])
    assert args.command == "scan"
    assert args.output == "./.ragops/manuals"
    assert args.skip_manuals is False
    assert args.incremental is False
    assert args.base_ref == "HEAD"


def test_init_parser_defaults_to_sqlite_local_backend() -> None:
    parser = build_parser()
    args = parser.parse_args(["init"])
    assert args.command == "init"
    assert args.storage_backend == "sqlite"
    assert args.local_db_path == ".ragops/ragops.db"
    assert args.no_global_config is False


def test_config_show_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["config", "show"])
    assert args.command == "config"
    assert args.config_command == "show"
    assert args.reveal_secrets is False


def test_config_set_parser_values() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "config",
            "set",
            "--openai-api-key",
            "abc123",
            "--storage-backend",
            "sqlite",
            "--local-db-path",
            ".ragops/my.db",
            "--llm-enabled",
            "true",
        ]
    )
    assert args.command == "config"
    assert args.config_command == "set"
    assert args.openai_api_key == "abc123"
    assert args.storage_backend == "sqlite"
    assert args.local_db_path == ".ragops/my.db"
    assert args.llm_enabled == "true"


def test_config_doctor_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["config", "doctor"])
    assert args.command == "config"
    assert args.config_command == "doctor"
    assert args.json is False
    assert args.fix is False


def test_config_doctor_parser_fix_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["config", "doctor", "--fix"])
    assert args.fix is True
