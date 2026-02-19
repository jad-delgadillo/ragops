# Codebase Manual

Generated at: 2026-02-19 06:07:50Z

## Project
- Name: `ragops`
- Tech stack: Python, Docker, Terraform
- Analyzer scope: file tree (depth <= 3), key entrypoints, Python AST symbols

## File Map (Preview)
- `.ragops/repos/openclaw-openclaw/tsdown.config.ts`
- `.ragops/repos/openclaw-openclaw/vitest.config.ts`
- `.ragops/repos/openclaw-openclaw/vitest.e2e.config.ts`
- `.ragops/repos/openclaw-openclaw/vitest.extensions.config.ts`
- `.ragops/repos/openclaw-openclaw/vitest.gateway.config.ts`
- `.ragops/repos/openclaw-openclaw/vitest.live.config.ts`
- `.ragops/repos/openclaw-openclaw/vitest.unit.config.ts`
- `frontend/app.js`
- `scripts/init_neon.py`
- `scripts/local_api.py`
- `scripts/mock_chat_api.py`
- `services/__init__.py`
- `services/api/__init__.py`
- `services/api/app/__init__.py`
- `services/api/app/access.py`
- `services/api/app/chat.py`
- `services/api/app/handler.py`
- `services/api/app/repo_onboarding.py`
- `services/api/app/retriever.py`
- `services/api/tests/__init__.py`
- `services/api/tests/test_access.py`
- `services/api/tests/test_chat.py`
- `services/api/tests/test_retriever.py`
- `services/cli/__init__.py`
- `services/cli/docgen/__init__.py`
- `services/cli/docgen/analyzer.py`
- `services/cli/docgen/generator.py`
- `services/cli/docgen/manuals.py`
- `services/cli/eval.py`
- `services/cli/main.py`
- `services/cli/project.py`
- `services/cli/remote.py`
- `services/cli/repositories.py`
- `services/cli/tests/__init__.py`
- `services/cli/tests/test_chat_shell_ui.py`
- `services/cli/tests/test_cli_config_commands.py`
- `services/cli/tests/test_cli_parser.py`
- `services/cli/tests/test_eval.py`
- `services/cli/tests/test_manuals.py`
- `services/cli/tests/test_repositories.py`
- `services/cli/tests/test_user_config.py`
- `services/cli/user_config.py`
- `services/core/__init__.py`
- `services/core/bedrock_provider.py`
- `services/core/claude_provider.py`
- `services/core/config.py`
- `services/core/database.py`
- `services/core/gemini_provider.py`
- `services/core/github_tree.py`
- `services/core/groq_provider.py`
- `services/core/logging.py`
- `services/core/ollama_provider.py`
- `services/core/openai_provider.py`
- `services/core/providers.py`
- `services/core/storage.py`
- `services/core/tests/__init__.py`
- `services/core/tests/test_database.py`
- `services/core/tests/test_providers.py`
- `services/core/tests/test_storage.py`
- `services/ingest/__init__.py`
- `services/ingest/app/__init__.py`
- `services/ingest/app/chunker.py`
- `services/ingest/app/handler.py`
- `services/ingest/app/pipeline.py`
- `services/ingest/tests/__init__.py`
- `services/ingest/tests/test_chunker.py`
- `services/ingest/tests/test_pipeline.py`

## Key Symbols
### `services/api/app/handler.py`
- Function `lambda_handler`
- Function `_handle_health`
- Function `_handle_query`
- Function `_handle_chat`
- Function `_handle_feedback`
- Function `_as_bool`
- Function `_handle_repo_onboard`
- Function `_handle_repo_onboard_status`
- Function `_execute_repo_onboard`
- Function `_resolve_repo_onboard_worker_function`
- Function `_dispatch_repo_onboard_job`
- Function `_run_repo_onboard_job`
- Function `_handle_repo_onboard_job_event`
- Function `_authorize`
- Function `_forbidden`
- Function `_with_cors`
- Function `main`
### `services/cli/main.py`
- Class `_ChatShellTurn` (no methods)
- Function `_read_env_value`
- Function `_upsert_env_values`
- Function `_apply_user_profile_defaults`
- Function `cmd_init`
- Function `cmd_ingest`
- Function `cmd_scan`
- Function `cmd_query`
- Function `_ragops_version`
- Function `_shell_clock`
- Function `_format_chat_provider_label`
- Function `_shorten_home`
- Function `_citation_summary`
- Function `_parse_chat_shell_command`
- Function `_render_chat_shell`
- Function `cmd_chat`
- Function `cmd_feedback`
- Function `cmd_eval`
- Function `cmd_generate_docs`
- Function `cmd_generate_manuals`
- Function `_repo_ingest_and_manuals`
- Function `cmd_repo_add`
- Function `cmd_repo_add_lazy`
- Function `cmd_repo_sync`
- Function `cmd_repo_list`
- Function `cmd_repo_migrate_collections`
- Function `_mask_secret`
- Function `cmd_config_show`
- Function `cmd_config_set`
- Function `cmd_config_doctor`
- Function `cmd_providers`
- Function `build_parser`
- Function `main`
### `services/ingest/app/handler.py`
- Function `lambda_handler`
- Function `_handle_repo_onboard_job_event`
- Function `main`

## Onboarding Notes
1. Start with `services/cli/main.py` to understand developer workflow.
2. Review `services/ingest` for indexing pipeline behavior.
3. Review `services/api` for runtime query behavior and response contract.
4. Review `services/core` for provider, config, and database abstractions.
